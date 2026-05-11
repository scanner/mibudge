"""
Budget funding engine -- Phase 6.

Entry point:
    fund_account(account, today, actor) -> FundingReport

The engine processes two event types per budget:

  Fund events   -- fire on budget.funding_schedule.
                   Transfer money from the account's unallocated budget
                   into the target budget (or its fillup_goal for
                   Recurring budgets).

  Recur events  -- fire on budget.recurrence_schedule.
                   Only for Recurring budgets.
                   Transfer from fillup_goal into the recurring budget
                   up to its target_balance; set complete if funded.

Events are sorted in (date asc, fund-before-recur) order so that a
multi-period catch-up reproduces the sequence that would have occurred
with no delay.

The import-freshness gate defers the entire account if
account.last_posted_through is behind the latest due event date,
ensuring the engine never runs ahead of confirmed transaction data.
"""

# system imports
#
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal

# 3rd party imports
#
import recurrence as recurrence_lib
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction as db_transaction
from djmoney.money import Money

# Project imports
#
from moneypools.models import BankAccount, Budget
from moneypools.service import internal_transaction as internal_transaction_svc

logger = logging.getLogger(__name__)

User = get_user_model()

_KIND_FUND: Literal["fund"] = "fund"
_KIND_RECUR: Literal["recur"] = "recur"
_KIND_ORDER = {_KIND_FUND: 0, _KIND_RECUR: 1}


########################################################################
########################################################################
#
@dataclass
class FundingEvent:
    """A single scheduled event to process.

    Attributes:
        date: Calendar date the event falls on.
        kind: 'fund' for a funding event, 'recur' for a recurrence event.
        budget: The Budget this event belongs to.
    """

    date: date
    kind: Literal["fund", "recur"]
    budget: Budget

    def sort_key(self) -> tuple:
        return (self.date, _KIND_ORDER[self.kind], str(self.budget.id))


########################################################################
########################################################################
#
@dataclass
class FundingReport:
    """Summary returned by fund_account().

    Attributes:
        account_id: UUID string of the processed account.
        deferred: True when the import-freshness gate blocked processing.
        transfers: Number of InternalTransaction rows created.
        warnings: Human-readable warning strings (cap events, etc.).
        skipped_budgets: Names of paused/archived budgets that were skipped.
    """

    account_id: str
    deferred: bool = False
    transfers: int = 0
    warnings: list[str] = field(default_factory=list)
    skipped_budgets: list[str] = field(default_factory=list)


########################################################################
########################################################################
#
@dataclass
class NextFundingInfo:
    """The next scheduled funding event for a budget.

    Attributes:
        date: Calendar date of the next funding event.
        amount: Money amount that will be transferred.
        deferred: True when the import-freshness gate would delay this event.
    """

    date: date
    amount: Money
    deferred: bool = False


########################################################################
########################################################################
#
def next_funding_info(
    budget: Budget,
    today: date | None = None,
) -> NextFundingInfo | None:
    """Return the next scheduled funding event for a budget, or None.

    Returns None for:
    - Paused or archived budgets
    - Completed GOAL budgets
    - RECURRING budgets with a fill-up goal (funded indirectly via fill-up)
    - Budgets with no upcoming events
    - CAPPED budgets already at their target (amount would be zero)

    For ASSOCIATED_FILLUP_GOAL budgets, the parent RECURRING budget's
    schedule and parameters are used to compute the event.

    Args:
        budget: The Budget to inspect.
        today: Reference date for event enumeration (defaults to date.today()).

    Returns:
        NextFundingInfo with the next event's date, amount, and deferred flag,
        or None if no event is due or applicable.
    """
    if today is None:
        today = date.today()

    if budget.paused or budget.archived:
        return None

    if budget.budget_type == Budget.BudgetType.GOAL and budget.complete:
        return None

    # RECURRING budgets are funded indirectly via their fill-up goal;
    # the recurring budget itself has no direct funding events.
    if budget.budget_type == Budget.BudgetType.RECURRING:
        return None

    # For ASSOCIATED_FILLUP_GOAL, delegate to the parent RECURRING budget's
    # schedule while using this budget as the target for amount calculations.
    if budget.budget_type == Budget.BudgetType.ASSOCIATED_FILLUP_GOAL:
        parent = (
            Budget.objects.filter(fillup_goal=budget)
            .select_related("bank_account")
            .first()
        )
        if parent is None or parent.paused or parent.archived:
            return None
        scheduling_budget = parent
        target = budget
    else:
        scheduling_budget = budget
        target = budget

    account = scheduling_budget.bank_account

    if scheduling_budget.last_funded_on is not None:
        after = scheduling_budget.last_funded_on
    else:
        # Mirror _collect_events: push back to one day before the most recent
        # funding boundary so that past-due catch-up events are included.
        prev = _prev_recurrence_boundary(
            scheduling_budget.funding_schedule,
            scheduling_budget.created_at.date(),
        )
        after = (
            prev - timedelta(days=1)
            if prev is not None
            else scheduling_budget.created_at.date()
        )
    # Look ahead up to 2 years to find the next event.
    look_ahead = date(today.year + 2, today.month, today.day)
    upcoming = _enumerate_schedule(
        scheduling_budget.funding_schedule, after, look_ahead
    )
    if not upcoming:
        return None

    next_date = upcoming[0]

    amount = _calculate_fund_amount(scheduling_budget, target, next_date, today)
    if amount.amount <= Decimal("0"):
        return None

    # An event is deferred whenever the account's import data isn't current
    # through the event date -- regardless of whether the event is past or
    # future.  A future event with stale data will fail the gate when its
    # date arrives; showing it as deferred now avoids a false sense of
    # certainty.
    deferred = (
        account.last_posted_through is None
        or account.last_posted_through < next_date
    )

    return NextFundingInfo(date=next_date, amount=amount, deferred=deferred)


########################################################################
########################################################################
#
def funding_system_user() -> User:  # type: ignore[valid-type]
    """Return the non-loginable funding-system user.

    Returns:
        The User instance with username 'funding-system'.

    Raises:
        User.DoesNotExist: If the data migration has not been run.
    """
    return User.objects.get(username=settings.FUNDING_SYSTEM_USERNAME)


####################################################################
#
def fund_account(
    account: BankAccount,
    today: date,
    actor: User,  # type: ignore[valid-type]
) -> FundingReport:
    """Process all due funding and recurrence events for one account.

    Applies the import-freshness gate, collects due events, sorts them
    in date-grouped order (fund before recur per date, budget.id
    tiebreak), and dispatches each event.  All balance changes flow
    through internal_transaction_svc so the budget-balance invariant
    is maintained.

    Args:
        account: The BankAccount to fund.
        today: The date to treat as 'today' (allows back-fill via CLI).
        actor: The User recorded as actor on generated InternalTransactions.

    Returns:
        A FundingReport describing what was done (or why it was deferred).
    """
    report = FundingReport(account_id=str(account.id))

    budgets = list(
        Budget.objects.filter(
            bank_account=account,
            archived=False,
        ).select_related("fillup_goal")
    )

    events = _collect_events(budgets, today)
    if not events:
        return report

    gate_date = max(ev.date for ev in events)
    if (
        account.last_posted_through is None
        or account.last_posted_through < gate_date
    ):
        report.deferred = True
        logger.info(
            "fund_account: account %s deferred -- last_posted_through=%s, "
            "gate_date=%s",
            account.id,
            account.last_posted_through,
            gate_date,
        )
        return report

    events.sort(key=lambda ev: ev.sort_key())

    unallocated = account.unallocated_budget
    if unallocated is None:
        logger.warning(
            "fund_account: account %s has no unallocated budget; skipping.",
            account.id,
        )
        return report

    for ev in events:
        budget = ev.budget
        if budget.paused:
            if budget.name not in report.skipped_budgets:
                report.skipped_budgets.append(budget.name)
            # Advance the pointer so accumulated events are consumed; when
            # unpaused, only future events fire rather than a backlog.
            if ev.kind == _KIND_FUND:
                Budget.objects.filter(pkid=budget.pkid).update(
                    last_funded_on=ev.date
                )
            else:
                Budget.objects.filter(pkid=budget.pkid).update(
                    last_recurrence_on=ev.date
                )
            continue

        if ev.kind == _KIND_FUND:
            _process_fund_event(ev, account, unallocated, actor, report, today)
        else:
            _process_recur_event(ev, account, actor, report)

    return report


########################################################################
########################################################################
#
def funding_event_dates(
    account: BankAccount,
    after: date,
    before: date,
) -> list[date]:
    """Return sorted unique dates with due funding events in (after, before].

    Args:
        account: The BankAccount to inspect.
        after: Exclusive lower bound (events strictly after this date).
        before: Inclusive upper bound (events up to and including this date).

    Returns:
        Sorted list of unique dates that have at least one due funding event.
    """
    budgets = list(
        Budget.objects.filter(
            bank_account=account,
            archived=False,
        ).select_related("fillup_goal")
    )
    events = _collect_events(budgets, before)
    return sorted({ev.date for ev in events if after < ev.date <= before})


########################################################################
########################################################################
#
def _collect_events(budgets: list[Budget], today: date) -> list[FundingEvent]:
    """
    Enumerate all due funding and recurrence events for a set of budgets.

    Args:
        budgets: Budgets to inspect (already filtered to non-archived).
        today: Upper bound (inclusive) for event enumeration.

    Returns:
        Unsorted list of FundingEvent objects.
    """
    events: list[FundingEvent] = []

    for budget in budgets:
        # Fill-up goal children are funded indirectly via their parent's fund
        # events; they do not generate their own events so they are skipped
        # here.
        #
        if budget.budget_type == Budget.BudgetType.ASSOCIATED_FILLUP_GOAL:
            continue

        # Once a budget of type GOAL is completed, it is never funded again.
        #
        if budget.budget_type == Budget.BudgetType.GOAL and budget.complete:
            continue

        if budget.last_funded_on is not None:
            fund_after = budget.last_funded_on
        else:
            # When no fund event has ever been processed, anchor to the most
            # recent schedule boundary at or before the budget's creation date
            # so events that fell between DTSTART and created_at are not
            # silently skipped.
            prev = _prev_recurrence_boundary(
                budget.funding_schedule, budget.created_at.date()
            )
            fund_after = (
                prev - timedelta(days=1)
                if prev is not None
                else budget.created_at.date()
            )
        for d in _enumerate_schedule(
            budget.funding_schedule, fund_after, today
        ):
            events.append(FundingEvent(date=d, kind=_KIND_FUND, budget=budget))

        if (
            budget.budget_type == Budget.BudgetType.RECURRING
            and budget.fillup_goal is not None
            and budget.recurrence_schedule
        ):
            if budget.last_recurrence_on is not None:
                recur_after = budget.last_recurrence_on
            else:
                # When no recurrence has ever been processed, anchor to the
                # most recent cycle boundary at or before the budget's
                # creation date. This ensures a recurrence that fell between
                # the schedule's DTSTART and created_at is not silently
                # skipped just because the Django object was created after it.
                prev = _prev_recurrence_boundary(
                    budget.recurrence_schedule, budget.created_at.date()
                )
                recur_after = (
                    prev - timedelta(days=1)
                    if prev is not None
                    else budget.created_at.date()
                )
            for d in _enumerate_schedule(
                budget.recurrence_schedule, recur_after, today
            ):
                events.append(
                    FundingEvent(date=d, kind=_KIND_RECUR, budget=budget)
                )

    return events


####################################################################
#
def _enumerate_schedule(
    sched: recurrence_lib.Recurrence | None,
    after: date,
    before: date,
) -> list[date]:
    """Return all dates on a recurrence schedule in (after, before].

    Args:
        sched: A recurrence.Recurrence object, or None.
        after: Exclusive lower bound (last processed date).
        before: Inclusive upper bound (today).

    Returns:
        Sorted list of dates strictly after *after* and <= *before*.
    """
    if not sched:
        return []

    # The recurrence library uses naive datetimes internally; passing
    # timezone-aware datetimes causes a TypeError on the internal comparison.
    after_dt = datetime(after.year, after.month, after.day)
    before_dt = datetime(before.year, before.month, before.day, 23, 59, 59)

    # Use the schedule's stored dtstart if present; fall back to after_dt so
    # the rule fires on the same day-of-month as the last-processed date rather
    # than defaulting to datetime.now() (which is non-deterministic).
    # Strip timezone: the stored dtstart comes back as UTC-aware after DB
    # round-trip, but the recurrence library uses naive datetimes internally.
    raw = sched.dtstart
    dtstart = raw.replace(tzinfo=None) if raw is not None else after_dt

    try:
        occurrences = list(
            sched.between(after_dt, before_dt, inc=False, dtstart=dtstart)
        )
    except (recurrence_lib.RecurrenceError, TypeError, ValueError) as exc:
        logger.warning("_enumerate_schedule: recurrence error: %r", exc)
        return []

    results = []
    for occ in occurrences:
        d = occ.date() if hasattr(occ, "date") else occ
        if after < d <= before:
            results.append(d)

    return sorted(set(results))


########################################################################
########################################################################
#
def _process_fund_event(
    ev: FundingEvent,
    account: BankAccount,
    unallocated: Budget,
    actor: User,  # type: ignore[valid-type]
    report: FundingReport,
    today: date,
) -> None:
    """
    Transfer funds from unallocated into the target budget.

    For Recurring budgets, the target is the fillup_goal.
    Otherwise the target is the budget itself.  Caps at unallocated balance.
    Advances last_funded_on unless unallocated is completely empty, in which
    case the event retries on the next run.  Partial (capped) transfers still
    advance the pointer; recovery happens at the next scheduled event.

    Args:
        ev: The funding event to process.
        account: The parent BankAccount.
        unallocated: The account's unallocated budget.
        actor: User for the InternalTransaction actor field.
        report: Mutable FundingReport to update.
        today: Used for TARGET_DATE gap-spread calculation.
    """
    budget = ev.budget

    target = (
        budget.fillup_goal
        if (
            budget.budget_type == Budget.BudgetType.RECURRING
            and budget.fillup_goal is not None
        )
        else budget
    )

    unallocated.refresh_from_db()
    target.refresh_from_db()

    amount = _calculate_fund_amount(budget, target, ev.date, today)
    if amount.amount <= Decimal("0"):
        Budget.objects.filter(pkid=budget.pkid).update(last_funded_on=ev.date)
        return

    available = unallocated.balance.amount
    if available <= Decimal("0"):
        report.warnings.append(
            f"[{ev.date}] {budget.name}: unallocated is empty; will retry."
        )
        return

    if amount.amount > available:
        report.warnings.append(
            f"[{ev.date}] {budget.name}: wanted {amount}, "
            f"only {unallocated.balance} available; capped."
        )
        amount = Money(available, amount.currency)

    # Use the event date as effective_date so the InternalTransaction
    # slots into the correct position in the historical timeline when
    # running a backfill for past periods.
    effective_date = datetime(
        ev.date.year, ev.date.month, ev.date.day, tzinfo=UTC
    )

    with db_transaction.atomic():
        internal_transaction_svc.create(
            bank_account=account,
            src_budget=unallocated,
            dst_budget=target,
            amount=amount,
            actor=actor,
            effective_date=effective_date,
        )

    Budget.objects.filter(pkid=budget.pkid).update(last_funded_on=ev.date)
    report.transfers += 1

    logger.debug(
        "fund_account: funded %s -> %s  amount=%s  date=%s",
        unallocated.name,
        target.name,
        amount,
        ev.date,
    )


####################################################################
#
def _prev_recurrence_boundary(
    sched: recurrence_lib.Recurrence | None,
    as_of: date,
) -> date | None:
    """Return the most recent occurrence of sched on or before as_of.

    Used to find the start of the current recurrence cycle for fill-up goals.

    Args:
        sched: The recurrence schedule.
        as_of: Date to search up to (inclusive).

    Returns:
        Most recent occurrence date, or None if none found within 2 years.
    """
    if not sched:
        return None

    start_dt = datetime(as_of.year - 2, as_of.month, as_of.day)
    end_dt = datetime(as_of.year, as_of.month, as_of.day, 23, 59, 59)

    raw = sched.dtstart
    dtstart = raw.replace(tzinfo=None) if raw is not None else start_dt

    try:
        occurrences = list(
            sched.between(start_dt, end_dt, inc=True, dtstart=dtstart)
        )
        if not occurrences:
            return None
        last = occurrences[-1]
        return (
            last.date()
            if hasattr(last, "date")
            else date(last.year, last.month, last.day)
        )
    except (recurrence_lib.RecurrenceError, TypeError, ValueError) as exc:
        logger.warning("_prev_recurrence_boundary: recurrence error: %r", exc)
        return None


####################################################################
#
def _fill_amount_prorated(
    budget: Budget,
    target: Budget,
    event_date: date,
    cycle_start: date,
    cycle_before: date,
) -> Money:
    """Compute the steady-state deposit toward a budget's target for one event.

    Divides the cycle into N total funding events and transfers 1/N of the
    target balance per event, capped at the remaining gap.  This gives a
    predictable per-event amount and stops once the target is reached.

    Example: target_balance=$100, N=2 events per cycle (15th and last day).
      - Each event transfers min($50, remaining_gap).
      - If target has $5: amount=min($50, $95)=$50.
      - If target has $60 (ahead): amount=min($50, $40)=$40.
      - If target has $95 (nearly full): amount=min($50, $5)=$5.
      - If target has $100: full_gap=0, returns $0.

    Args:
        budget: Budget whose funding_schedule defines the event cadence.
        target: Budget being funded (may equal budget for direct-funded cases).
        event_date: The funding event date (kept for API compatibility).
        cycle_start: Exclusive lower bound for counting all events in the cycle.
        cycle_before: Inclusive upper bound for counting all events in the cycle.

    Returns:
        Money amount to transfer, >= 0.
    """
    currency = target.balance.currency
    zero = Money(Decimal("0"), currency)

    full_gap = target.target_balance.amount - target.balance.amount
    if full_gap <= Decimal("0"):
        return zero

    sched = budget.funding_schedule
    if not sched:
        return Money(full_gap, currency)

    after_dt = datetime(cycle_start.year, cycle_start.month, cycle_start.day)
    before_dt = datetime(
        cycle_before.year, cycle_before.month, cycle_before.day, 23, 59, 59
    )

    raw = sched.dtstart
    raw_clean = raw.replace(tzinfo=None) if raw is not None else None
    # Use the earlier of the schedule's DTSTART and cycle_start as the
    # effective dtstart.  For theoretical prior cycles (e.g. a yearly budget
    # in its first annual cycle where the funding schedule's DTSTART is later
    # than the theoretical cycle start), this ensures events from the start of
    # the full cycle are counted rather than only events after DTSTART.
    effective_dtstart = (
        min(raw_clean, after_dt) if raw_clean is not None else after_dt
    )

    try:
        occs = list(
            sched.between(
                after_dt, before_dt, inc=False, dtstart=effective_dtstart
            )
        )
    except (recurrence_lib.RecurrenceError, TypeError, ValueError) as exc:
        logger.warning("_fill_amount_prorated: recurrence error: %r", exc)
        return Money(full_gap, currency)

    results = []
    for occ in occs:
        d = (
            occ.date()
            if hasattr(occ, "date")
            else date(occ.year, occ.month, occ.day)
        )
        if cycle_start < d <= cycle_before:
            results.append(d)

    N = len(sorted(set(results)))
    if N == 0:
        return Money(full_gap, currency)

    steady_state = (target.target_balance.amount / Decimal(N)).quantize(
        Decimal("0.01")
    )
    per_event = min(steady_state, full_gap)
    return Money(per_event, currency)


####################################################################
#
def _calculate_fund_amount(
    budget: Budget,
    target: Budget,
    event_date: date,
    today: date,
) -> Money:
    """Compute how much to transfer on a fund event.

    Args:
        budget: The source budget (determines funding type and schedule).
        target: The destination budget (used for balance/target checks).
        event_date: The date of this specific event.
        today: The reference date for TARGET_DATE calculations.

    Returns:
        A Money amount >= 0 to transfer.
    """
    currency = target.balance.currency
    zero = Money(Decimal("0"), currency)

    if budget.funding_type == Budget.FundingType.FIXED_AMOUNT:
        if budget.funding_amount is None:
            return zero
        amount = budget.funding_amount

        # For Capped budgets, never overfill.
        if budget.budget_type == Budget.BudgetType.CAPPED:
            gap = target.target_balance.amount - target.balance.amount
            if gap <= Decimal("0"):
                return zero
            amount = Money(min(amount.amount, gap), currency)

        return amount

    gap = target.target_balance.amount - target.balance.amount
    if gap <= Decimal("0"):
        return zero

    # RECURRING budgets: spread the gap over events in the current recurrence
    # cycle using a prorated cumulative target.  Applies whether the target is
    # the budget itself or its associated fill-up goal.
    if (
        budget.budget_type == Budget.BudgetType.RECURRING
        and budget.recurrence_schedule
    ):
        cycle_end = _next_recurrence_boundary(
            budget.recurrence_schedule, event_date + timedelta(days=1)
        )
        if cycle_end is not None:
            _prev = _prev_recurrence_boundary(
                budget.recurrence_schedule, event_date
            )
            cycle_start = (
                _prev or budget.last_recurrence_on or budget.created_at.date()
            )
            if _prev is None and budget.last_recurrence_on is None:
                # First cycle: the schedule's DTSTART hasn't been reached yet
                # so _prev_recurrence_boundary returns None.  Compute the
                # theoretical prior boundary by projecting the rule backward
                # using cycle_end's month/day as the anchor -- this preserves
                # the correct day-of-year for YEARLY rules and day-of-month
                # for MONTHLY rules.  Without this, N counts only the
                # remaining events (e.g., 8) instead of the full cycle
                # (e.g., 23), inflating the per-event amount.
                early_anchor = datetime(
                    cycle_end.year - 3, cycle_end.month, cycle_end.day
                )
                one_before = cycle_end - timedelta(days=1)
                end_search = datetime(
                    one_before.year,
                    one_before.month,
                    one_before.day,
                    23,
                    59,
                    59,
                )
                try:
                    prior_occs = list(
                        budget.recurrence_schedule.between(
                            early_anchor,
                            end_search,
                            inc=True,
                            dtstart=early_anchor,
                        )
                    )
                    if prior_occs:
                        last_occ = prior_occs[-1]
                        theoretical_start = (
                            last_occ.date()
                            if hasattr(last_occ, "date")
                            else date(
                                last_occ.year, last_occ.month, last_occ.day
                            )
                        )
                        cycle_start = theoretical_start
                except (recurrence_lib.RecurrenceError, TypeError, ValueError):
                    pass
            if cycle_start >= cycle_end:
                # event_date falls before the first recurrence boundary (e.g.,
                # a catch-up funding event on April 30 with DTSTART May 1).
                # Use the first full cycle's event count as the rate basis so
                # _fill_amount_prorated doesn't fall back to N=0 → full_gap.
                #
                # Use _enumerate_schedule (inc=False) instead of
                # _next_recurrence_boundary here: the boundary helper subtracts
                # one day before calling between(), which causes it to return
                # cycle_end itself when dtstart == cycle_end.
                look_ahead = date(
                    cycle_end.year + 2, cycle_end.month, cycle_end.day
                )
                future = _enumerate_schedule(
                    budget.recurrence_schedule, cycle_end, look_ahead
                )
                if future:
                    next_cycle_end = future[0]
                    return _fill_amount_prorated(
                        budget,
                        target,
                        event_date,
                        cycle_end - timedelta(days=1),
                        next_cycle_end - timedelta(days=1),
                    )
            return _fill_amount_prorated(
                budget,
                target,
                event_date,
                cycle_start,
                cycle_end - timedelta(days=1),
            )

    # GOAL with target_date: the balance accumulates permanently, so divide the
    # full remaining gap evenly over all events between now and target_date.
    if budget.target_date is not None:
        remaining = _count_remaining_occurrences(
            budget.funding_schedule, event_date, budget.target_date
        )
        per_event = (gap / max(remaining, 1)).quantize(Decimal("0.01"))
        return Money(per_event, currency)

    # Fallback: no cycle boundaries available; deposit full remaining gap.
    return Money(gap, currency)


####################################################################
#
def _next_recurrence_boundary(
    sched: recurrence_lib.Recurrence | None,
    from_date: date,
) -> date | None:
    """Return the first date the recurrence schedule fires on or after from_date.

    Used to find the next cycle-reset boundary for RECURRING budgets, so
    gap-spreading is capped at the upcoming reset rather than an arbitrary date.

    Args:
        sched: The recurrence schedule (e.g. monthly-on-the-1st).
        from_date: Lower bound (inclusive).

    Returns:
        Next occurrence date, or None if none found within 2 years.
    """
    if not sched:
        return None

    # Search up to 2 years out; subtract one day so from_date itself is included
    # (between() is exclusive on the lower bound).
    start_dt = datetime(
        from_date.year, from_date.month, from_date.day
    ) - timedelta(days=1)
    look_ahead = date(from_date.year + 2, from_date.month, from_date.day)
    end_dt = datetime(
        look_ahead.year, look_ahead.month, look_ahead.day, 23, 59, 59
    )

    raw = sched.dtstart
    dtstart = raw.replace(tzinfo=None) if raw is not None else start_dt

    try:
        occurrences = sched.between(start_dt, end_dt, inc=True, dtstart=dtstart)
        first = next(iter(occurrences), None)
        if first is None:
            return None
        return (
            first.date()
            if hasattr(first, "date")
            else date(first.year, first.month, first.day)
        )
    except (recurrence_lib.RecurrenceError, TypeError, ValueError) as exc:
        logger.warning("_next_recurrence_boundary: recurrence error: %r", exc)
        return None


####################################################################
#
def _count_remaining_occurrences(
    sched: recurrence_lib.Recurrence | None,
    from_date: date,
    end_date: date,
) -> int:
    """Count occurrences of a schedule from from_date (inclusive) to end_date.

    Used for TARGET_DATE gap-spreading: divide remaining gap by this count.

    Args:
        sched: The funding schedule.
        from_date: Start date (inclusive).
        end_date: Upper bound (inclusive); pass budget.target_date for Goals.

    Returns:
        Number of occurrences in [from_date, end_date] (minimum 1).
    """
    if not sched:
        return 1

    # between() is exclusive on the lower bound; subtract one day so
    # from_date itself is included.  Use naive datetimes (library requirement).
    start_dt = datetime(
        from_date.year, from_date.month, from_date.day
    ) - timedelta(days=1)
    end_dt = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59)

    raw = sched.dtstart
    dtstart = raw.replace(tzinfo=None) if raw is not None else start_dt

    try:
        occurrences = list(
            sched.between(start_dt, end_dt, inc=True, dtstart=dtstart)
        )
    except (recurrence_lib.RecurrenceError, TypeError, ValueError) as exc:
        logger.warning(
            "_count_remaining_occurrences: recurrence error: %r", exc
        )
        return 1

    return max(1, len(occurrences))


########################################################################
########################################################################
#
def _process_recur_event(
    ev: FundingEvent,
    account: BankAccount,
    actor: User,  # type: ignore[valid-type]
    report: FundingReport,
) -> None:
    """Transfer from fillup_goal into the recurring budget up to target.

    Sets budget.complete if the recurring budget reaches its target after
    the transfer.  Advances last_recurrence_on regardless.

    Args:
        ev: The recurrence event to process.
        account: The parent BankAccount.
        actor: User for the InternalTransaction actor field.
        report: Mutable FundingReport to update.
    """
    budget = ev.budget
    fillup = budget.fillup_goal
    if fillup is None:
        return

    budget.refresh_from_db()
    fillup.refresh_from_db()

    # Reset complete at the start of each new cycle.
    if budget.complete:
        Budget.objects.filter(pkid=budget.pkid).update(complete=False)
        budget.complete = False

    gap = budget.target_balance.amount - budget.balance.amount
    if gap <= Decimal("0"):
        Budget.objects.filter(pkid=budget.pkid).update(
            last_recurrence_on=ev.date,
            complete=True,
        )
        return

    fillup_available = fillup.balance.amount
    if fillup_available <= Decimal("0"):
        report.warnings.append(
            f"[{ev.date}] {budget.name}: fill-up goal is empty; will retry."
        )
        return

    transfer = min(gap, fillup_available)
    if transfer < gap:
        report.warnings.append(
            f"[{ev.date}] {budget.name}: fill-up only had "
            f"{fillup.balance}; needed {gap}; underfunded."
        )

    amount = Money(transfer, budget.balance.currency)
    effective_date = datetime(
        ev.date.year, ev.date.month, ev.date.day, tzinfo=UTC
    )

    with db_transaction.atomic():
        internal_transaction_svc.create(
            bank_account=account,
            src_budget=fillup,
            dst_budget=budget,
            amount=amount,
            actor=actor,
            effective_date=effective_date,
        )

    budget.refresh_from_db()
    newly_complete = budget.balance.amount >= budget.target_balance.amount
    Budget.objects.filter(pkid=budget.pkid).update(
        last_recurrence_on=ev.date,
        complete=newly_complete,
    )
    report.transfers += 1

    logger.debug(
        "fund_account: recur %s -> %s  amount=%s  date=%s  complete=%s",
        fillup.name,
        budget.name,
        amount,
        ev.date,
        newly_complete,
    )
