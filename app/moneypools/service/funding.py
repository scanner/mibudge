"""
Budget funding engine.

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
                   up to its target_balance; mark complete one-shot.

Events are sorted in (date asc, fund-before-recur) order so that a
multi-period catch-up reproduces the sequence that would have occurred
with no delay.

Each due event has a FundingEventOccurrence row whose status tracks
progress:

  PENDING  -- created, no transfer attempted yet.
  PARTIAL  -- transferred less than the strategy's intended amount;
              eligible for retry on subsequent runs until superseded.
  COMPLETE -- intended amount fully covered; Budget.last_funded_on /
              last_recurrence_on advance to this date.
  SKIPPED  -- closed without completion (budget paused at processing
              time, or superseded by a newer occurrence of the same
              (budget, kind)).

Concurrency: a non-blocking Redis lock on ``account.lock_key`` guards
the whole run.  A second concurrent caller (scheduled task vs.
"Run funding now" button) returns ``FundingReport(busy=True)`` rather
than wait or duplicate work.
"""

# system imports
#
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

# 3rd party imports
#
from django.db import transaction as db_transaction
from django.utils import timezone
from djmoney.money import Money

# Project imports
#
from common.locks import acquire_lock
from moneypools.models import (
    BankAccount,
    Budget,
    EventKind,
    FundingEventOccurrence,
    InternalTransaction,
)
from moneypools.notification_kinds import RECURRING_BUDGET_REFRESHED
from moneypools.service import internal_transaction as internal_transaction_svc
from moneypools.service.funding_strategy import BUDGET_TYPE_TO_STRATEGY
from moneypools.service.schedules import (
    enumerate_schedule,
    prev_recurrence_boundary,
)
from notifications.service import notify_for
from users.models import User

logger = logging.getLogger(__name__)

_KIND_ORDER = {EventKind.FUND: 0, EventKind.RECUR: 1}


########################################################################
########################################################################
#
@dataclass
class FundingEvent:
    """A single scheduled event to process.

    Attributes:
        date: Calendar date the event falls on.
        kind: FUND for a funding event, RECUR for a recurrence event.
        budget: The Budget this event belongs to.
    """

    date: date
    kind: EventKind
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
        busy: True when another worker held the account lock and this
            call returned without doing any work.
        transfers: Number of InternalTransaction rows created.
        warnings: Human-readable warning strings (cap events, etc.).
        skipped_budgets: Names of paused/archived budgets that were skipped.
        funded_budgets: Per-budget funding details accumulated during the run,
            used to build the FUNDING_COMPLETE notification.  Each entry is a
            dict with keys: budget_id, budget_name, amount_funded,
            total_funded, balance, target_balance, goal_reached, is_fillup.
        occurrences_completed: FundingEventOccurrence rows that reached
            COMPLETE during this run.
        occurrences_partial: FundingEventOccurrence rows left in PARTIAL
            (still owed money) at the end of this run.
    """

    account_id: str
    busy: bool = False
    transfers: int = 0
    warnings: list[str] = field(default_factory=list)
    skipped_budgets: list[str] = field(default_factory=list)
    funded_budgets: list[dict[str, Any]] = field(default_factory=list)
    occurrences_completed: int = 0
    occurrences_partial: int = 0


########################################################################
########################################################################
#
@dataclass
class NextFundingInfo:
    """The next scheduled funding event for a budget.

    Attributes:
        date: Calendar date of the next funding event.
        amount: Money amount that will be transferred.
    """

    date: date
    amount: Money


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
        NextFundingInfo with the next event's date and amount, or None
        if no event is due or applicable.
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
    else:
        scheduling_budget = budget

    if scheduling_budget.last_funded_on is not None:
        after = scheduling_budget.last_funded_on
    else:
        # Mirror _collect_events: push back to one day before the most recent
        # funding boundary so that past-due catch-up events are included.
        prev = prev_recurrence_boundary(
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
    upcoming = enumerate_schedule(
        scheduling_budget.funding_schedule, after, look_ahead
    )
    if not upcoming:
        return None

    next_date = upcoming[0]

    strategy = BUDGET_TYPE_TO_STRATEGY[scheduling_budget.budget_type]
    amount = strategy.intended_for_event(
        scheduling_budget, next_date, kind=EventKind.FUND
    )
    if amount.amount <= Decimal("0"):
        return None

    return NextFundingInfo(date=next_date, amount=amount)


####################################################################
#
def fund_account(
    account: BankAccount,
    today: date,
    actor: User,
    kinds: set[EventKind] | None = None,
) -> FundingReport:
    """Process due funding and recurrence events for one account.

    Acquires a non-blocking Redis lock on ``account.lock_key``.  If
    another worker holds the lock, returns immediately with
    ``report.busy = True``.

    Collects due events, sorts them in date-grouped order (fund before
    recur per date, budget.id tiebreak), ensures a
    FundingEventOccurrence instance exists per (budget, kind,
    scheduled_date), and dispatches each pending or partial event via
    its budget-type strategy.  All balance changes flow through
    internal_transaction_svc so the budget-balance invariant is
    maintained.

    When 'kinds' is given, only events of those types are processed.
    This lets the scheduler run FUND and RECUR events in separate passes
    at different times of day.

    Args:
        account: The BankAccount to fund.
        today: The date to treat as 'today' (allows back-fill via CLI).
        actor: The User recorded as actor on generated InternalTransactions.
        kinds: If given, restrict processing to these EventKind values.
            Pass None (the default) to process all event types together.

    Returns:
        A FundingReport describing what was done.  ``busy=True`` means
        another worker was already processing this account.
    """
    report = FundingReport(account_id=str(account.id))

    # Single-flight per account.  A second concurrent caller (scheduled
    # task vs. "Run funding now" button) bails out here rather than
    # interleave transfers with the in-flight run.
    #
    with acquire_lock(account.lock_key, blocking=False) as got_lock:
        if not got_lock:
            report.busy = True
            logger.info(
                "fund_account: account %s busy -- another worker holds "
                "the lock; skipping.",
                account.id,
            )
            return report

        # Active (non-archived) budgets on this account.  Archived budgets
        # never receive funding so they are filtered out at the source.
        #
        budgets = list(
            Budget.objects.filter(
                bank_account=account,
                archived=False,
            ).select_related("fillup_goal")
        )

        # Enumerate every due (budget, kind, date) tuple, optionally
        # restricted to the kinds the caller asked for (scheduled FUND
        # vs. scheduled RECUR run in separate passes).  Sort so that on
        # any given date FUND fires before RECUR -- the fill-up goal
        # must accumulate before the recurring budget sweeps it.
        #
        events = _collect_events(budgets, today)
        if kinds is not None:
            events = [ev for ev in events if ev.kind in kinds]
        if not events:
            return report

        events.sort(key=lambda ev: ev.sort_key())

        # Every fund event moves money out of the account's Unallocated
        # budget; without it there is no source to draw from.
        #
        unallocated = account.unallocated_budget
        if unallocated is None:
            logger.warning(
                "fund_account: account %s has no unallocated budget; skipping.",
                account.id,
            )
            return report

        # Ensure a FundingEventOccurrence instance exists for every
        # enumerated (budget, kind, scheduled_date); reuse existing rows
        # so a PARTIAL from a prior run carries its state into this one.
        #
        occurrence_for = _instantiate_occurrences(events)

        # Invariant: at most one occurrence per (budget, kind) is
        # active (PENDING or PARTIAL) at any time.  Process events in
        # date-sorted order; just before running event N, mark every
        # earlier-dated active occurrence for the same (budget, kind)
        # as SKIPPED -- their retry windows have closed now that a
        # newer event is taking over.  Occurrences already in a
        # terminal state are no-ops, which makes "Run funding now"
        # idempotent.  Paused budgets are checked here rather than at
        # instantiation so that flipping paused mid-run is consistent
        # regardless of the budget's pause state when the event date
        # passed.
        #
        for ev in events:
            key = (str(ev.budget.id), ev.kind.value, ev.date)
            occ = occurrence_for[key]
            if occ.status in (
                FundingEventOccurrence.Status.COMPLETE,
                FundingEventOccurrence.Status.SKIPPED,
            ):
                continue

            _close_prior_incomplete(ev.budget, ev.kind, ev.date)

            budget = ev.budget
            if budget.paused:
                if budget.name not in report.skipped_budgets:
                    report.skipped_budgets.append(budget.name)
                FundingEventOccurrence.objects.filter(pkid=occ.pkid).update(
                    status=FundingEventOccurrence.Status.SKIPPED,
                )
                continue

            if ev.kind == EventKind.FUND:
                _process_fund_event(
                    ev, occ, account, unallocated, actor, report
                )
            else:
                _process_recur_event(ev, occ, account, actor, report)

    return report


####################################################################
#
def _instantiate_occurrences(
    events: list["FundingEvent"],
) -> dict[tuple[str, str, date], FundingEventOccurrence]:
    """get_or_create a FundingEventOccurrence per enumerated event.

    Pure get_or_create.  A new row is created with status PENDING; an
    existing row (e.g. PARTIAL from a prior run) is returned unchanged
    so its state carries forward.

    Args:
        events: Enumerated funding/recurrence events for this run.

    Returns:
        Mapping of (budget_id_str, kind_value, scheduled_date) to the
        FundingEventOccurrence instance, so the processing loop can
        look up each event's occurrence without re-querying.
    """
    occurrence_for: dict[tuple[str, str, date], FundingEventOccurrence] = {}
    for ev in events:
        occ, _ = FundingEventOccurrence.objects.get_or_create(
            budget=ev.budget,
            kind=ev.kind.value,
            scheduled_date=ev.date,
            defaults={"status": FundingEventOccurrence.Status.PENDING},
        )
        occurrence_for[(str(ev.budget.id), ev.kind.value, ev.date)] = occ
    return occurrence_for


####################################################################
#
def _close_prior_incomplete(
    budget: Budget,
    kind: EventKind,
    before_date: date,
) -> None:
    """Enforce one-active-occurrence-per-(budget, kind).

    Marks every earlier-dated PENDING/PARTIAL occurrence of this
    (budget, kind) as SKIPPED so that ``before_date`` becomes the sole
    in-flight event.  No-op when there is nothing earlier to close.
    """
    FundingEventOccurrence.objects.filter(
        budget=budget,
        kind=kind.value,
        scheduled_date__lt=before_date,
        status__in=(
            FundingEventOccurrence.Status.PENDING,
            FundingEventOccurrence.Status.PARTIAL,
        ),
    ).update(status=FundingEventOccurrence.Status.SKIPPED)


####################################################################
#
def _mark_occurrence_complete(
    occurrence: FundingEventOccurrence,
    budget: Budget,
    kind: EventKind,
    scheduled_date: date,
    report: FundingReport,
) -> None:
    """Persist COMPLETE status and advance the matching Budget pointer.

    ``Budget.last_funded_on`` and ``Budget.last_recurrence_on`` are kept
    as denormalized caches of the most recent COMPLETE occurrence date
    for each kind, preserving the existing readers in ``_collect_events``
    and ``next_funding_info`` without needing a join against the
    occurrence table.
    """
    FundingEventOccurrence.objects.filter(pkid=occurrence.pkid).update(
        status=FundingEventOccurrence.Status.COMPLETE,
        completed_at=timezone.now(),
    )
    if kind == EventKind.FUND:
        Budget.objects.filter(pkid=budget.pkid).update(
            last_funded_on=scheduled_date
        )
    else:
        Budget.objects.filter(pkid=budget.pkid).update(
            last_recurrence_on=scheduled_date
        )
    report.occurrences_completed += 1


####################################################################
#
def _mark_occurrence_partial(
    occurrence: FundingEventOccurrence,
    report: FundingReport,
) -> None:
    """Persist PARTIAL status (idempotent) for an under-funded event."""
    if occurrence.status != FundingEventOccurrence.Status.PARTIAL:
        FundingEventOccurrence.objects.filter(pkid=occurrence.pkid).update(
            status=FundingEventOccurrence.Status.PARTIAL,
        )
    report.occurrences_partial += 1


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

    Catch-up events are in (last_pointer, today) exclusive.  Today's events
    always fire regardless of pointer position -- achieved by clamping
    fund_after / recur_after to at most today-1 before enumeration.

    Args:
        budgets: Budgets to inspect (already filtered to non-archived).
        today: Upper bound (inclusive) for event enumeration.

    Returns:
        Unsorted list of FundingEvent objects.
    """
    events: list[FundingEvent] = []
    today_minus_1 = today - timedelta(days=1)

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
            prev = prev_recurrence_boundary(
                budget.funding_schedule, budget.created_at.date()
            )
            fund_after = (
                prev - timedelta(days=1)
                if prev is not None
                else budget.created_at.date()
            )
        # Clamp so today always fires even when the pointer is already at today.
        fund_after = min(fund_after, today_minus_1)
        for d in enumerate_schedule(budget.funding_schedule, fund_after, today):
            events.append(
                FundingEvent(date=d, kind=EventKind.FUND, budget=budget)
            )

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
                prev = prev_recurrence_boundary(
                    budget.recurrence_schedule, budget.created_at.date()
                )
                recur_after = (
                    prev - timedelta(days=1)
                    if prev is not None
                    else budget.created_at.date()
                )
            # Clamp so today always fires even when the pointer is already at today.
            recur_after = min(recur_after, today_minus_1)
            for d in enumerate_schedule(
                budget.recurrence_schedule, recur_after, today
            ):
                events.append(
                    FundingEvent(date=d, kind=EventKind.RECUR, budget=budget)
                )

    return events


####################################################################
#
def _process_fund_event(
    ev: FundingEvent,
    occurrence: FundingEventOccurrence,
    account: BankAccount,
    unallocated: Budget,
    actor: User,
    report: FundingReport,
) -> None:
    """
    Transfer funds from unallocated into the target budget.

    For Recurring budgets, the target is the fillup_goal.  Otherwise
    the target is the budget itself.

    Computes already_moved (sum of prior system FUND ITXs for this
    event date) and transfers only the remainder of intended.  The
    occurrence row is updated to COMPLETE when the cumulative transfer
    covers the intended amount and to PARTIAL otherwise -- the latter
    leaves the event eligible for retry on a later run once funds become
    available.  ``Budget.last_funded_on`` is advanced only on COMPLETE.

    Args:
        ev: The funding event to process.
        occurrence: The FundingEventOccurrence row for this event.
        account: The parent BankAccount.
        unallocated: The account's unallocated budget.
        actor: User for the InternalTransaction actor field.
        report: Mutable FundingReport to update.
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
    budget.refresh_from_db()

    strategy = BUDGET_TYPE_TO_STRATEGY[budget.budget_type]
    intended = strategy.intended_for_event(budget, ev.date, kind=EventKind.FUND)

    already_moved = sum(
        (
            itx.amount.amount
            for itx in InternalTransaction.objects.filter(
                dst_budget=target,
                system_event_kind=InternalTransaction.SystemEventKind.FUND,
                system_event_date=ev.date,
            )
        ),
        Decimal("0"),
    )
    net = max(Decimal("0"), intended.amount - already_moved)

    # Nothing left to move (intended already covered by prior runs, or
    # intended was zero to begin with -- e.g. a Capped budget already at
    # target).  The event has done its job; mark it complete and advance.
    #
    if net <= Decimal("0"):
        _mark_occurrence_complete(
            occurrence, budget, EventKind.FUND, ev.date, report
        )
        return

    # No source funds available -- leave the occurrence PARTIAL so the
    # next run can top it up once Unallocated is replenished.
    #
    available = unallocated.balance.amount
    if available <= Decimal("0"):
        report.warnings.append(
            f"[{ev.date}] {budget.name}: unallocated is empty; transfer skipped."
        )
        _mark_occurrence_partial(occurrence, report)
        return

    # Partial coverage: transfer what we have and remember we still owe
    # the difference; the COMPLETE/PARTIAL decision below is driven by
    # the actual transferred amount, not the original intent.
    #
    capped = net > available
    transferred = min(net, available)
    if capped:
        report.warnings.append(
            f"[{ev.date}] {budget.name}: wanted "
            f"{Money(net, intended.currency)}, only {unallocated.balance} "
            "available; capped."
        )

    amount = Money(transferred, intended.currency)
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
            system_event_kind=InternalTransaction.SystemEventKind.FUND,
            system_event_date=ev.date,
        )

    target.refresh_from_db()
    # For GOAL budgets, internal_transaction_svc latches complete=True once
    # funded_amount >= target_balance; check the refreshed flag rather than
    # comparing balance (which can be lower due to pre-spending).
    goal_reached = bool(
        target.budget_type == Budget.BudgetType.GOAL and target.complete
    )
    report.funded_budgets.append(
        {
            "budget_id": str(target.id),
            "budget_name": target.name,
            "amount_funded": str(amount),
            "total_funded": str(target.funded_amount),
            "balance": str(target.balance),
            "target_balance": str(target.target_balance),
            "goal_reached": goal_reached,
            "is_fillup": target.budget_type
            == Budget.BudgetType.ASSOCIATED_FILLUP_GOAL,
        }
    )
    report.transfers += 1

    logger.debug(
        "fund_account: funded %s -> %s  amount=%s  date=%s",
        unallocated.name,
        target.name,
        amount,
        ev.date,
    )

    # COMPLETE if cumulative transfers now meet the intended amount;
    # otherwise PARTIAL and we will revisit on the next run.
    #
    if already_moved + transferred >= intended.amount:
        _mark_occurrence_complete(
            occurrence, budget, EventKind.FUND, ev.date, report
        )
    else:
        _mark_occurrence_partial(occurrence, report)


####################################################################
#
def _process_recur_event(
    ev: FundingEvent,
    occurrence: FundingEventOccurrence,
    account: BankAccount,
    actor: User,
    report: FundingReport,
) -> None:
    """Transfer from fillup_goal into the recurring budget up to target.

    The transfer is capped at the smaller of (a) the strategy's
    intended-amount (the gap from the recurring budget's current balance
    to its target) and (b) whatever the fill-up actually has on hand.
    Idempotent across same-day re-runs via the already_moved subtraction.

    RECUR is one-shot.  Regardless of whether the fill-up had enough to
    bring the recurring budget all the way to its target, the occurrence
    is marked COMPLETE at the end and ``Budget.last_recurrence_on`` is
    advanced.  Per the design, missed money does not get retried after
    the cycle boundary -- the next cycle starts fresh.

    Args:
        ev: The recurrence event to process.
        occurrence: The FundingEventOccurrence row for this event.
        account: The parent BankAccount.
        actor: User for the InternalTransaction actor field.
        report: Mutable FundingReport to update.
    """
    budget = ev.budget
    fillup = budget.fillup_goal
    if fillup is None:
        # Defensive: a RECUR event for a budget without a fill-up should
        # never have been enumerated.  Mark the occurrence COMPLETE so it
        # does not keep getting re-processed.
        #
        _mark_occurrence_complete(
            occurrence, budget, EventKind.RECUR, ev.date, report
        )
        return

    budget.refresh_from_db()
    fillup.refresh_from_db()

    # New cycle: clear the "complete" latch so the recurring budget can
    # be re-evaluated against its target as money sweeps in.
    #
    if budget.complete:
        Budget.objects.filter(pkid=budget.pkid).update(complete=False)
        budget.complete = False

    strategy = BUDGET_TYPE_TO_STRATEGY[budget.budget_type]
    intended = strategy.intended_for_event(
        budget, ev.date, kind=EventKind.RECUR
    )

    already_moved = sum(
        (
            itx.amount.amount
            for itx in InternalTransaction.objects.filter(
                dst_budget=budget,
                system_event_kind=InternalTransaction.SystemEventKind.RECUR,
                system_event_date=ev.date,
            )
        ),
        Decimal("0"),
    )
    net = max(Decimal("0"), intended.amount - already_moved)

    amount_received = Money(Decimal("0"), budget.balance.currency)

    # Sweep from fill-up to recurring, capped at min(gap-to-target,
    # fill-up balance).  If the fill-up is empty, we still mark the
    # occurrence COMPLETE below -- "clean break" semantics.
    #
    if net > Decimal("0"):
        fillup_available = fillup.balance.amount
        if fillup_available <= Decimal("0"):
            report.warnings.append(
                f"[{ev.date}] {budget.name}: fill-up goal is empty; "
                "transfer skipped."
            )
        else:
            transfer = min(net, fillup_available)
            if transfer < net:
                report.warnings.append(
                    f"[{ev.date}] {budget.name}: fill-up only had "
                    f"{fillup.balance}; needed "
                    f"{Money(net, budget.balance.currency)}; underfunded."
                )
            amount = Money(transfer, budget.balance.currency)
            amount_received = amount
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
                    system_event_kind=InternalTransaction.SystemEventKind.RECUR,
                    system_event_date=ev.date,
                )
            budget.refresh_from_db()
            report.transfers += 1
            logger.debug(
                "fund_account: recur %s -> %s  amount=%s  date=%s",
                fillup.name,
                budget.name,
                amount,
                ev.date,
            )

    # Latch Budget.complete based on whether the recurring budget hit
    # its target this cycle; this is independent of occurrence status.
    #
    newly_complete = budget.balance.amount >= budget.target_balance.amount
    Budget.objects.filter(pkid=budget.pkid).update(complete=newly_complete)

    # One-shot: occurrence is COMPLETE after a single pass, hit-or-miss
    # on the target.  This also advances Budget.last_recurrence_on.
    #
    _mark_occurrence_complete(
        occurrence, budget, EventKind.RECUR, ev.date, report
    )

    notify_for(
        account,
        RECURRING_BUDGET_REFRESHED,
        {
            "account_name": account.name,
            "account_id": str(account.id),
            "budget_id": str(budget.id),
            "budget_name": budget.name,
            "amount_received": str(amount_received),
            "balance": str(budget.balance),
            "target_balance": str(budget.target_balance),
            "goal_reached": newly_complete,
            "date": ev.date.isoformat(),
        },
    )
