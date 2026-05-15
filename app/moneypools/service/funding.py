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

# 3rd party imports
#
from django.contrib.auth import get_user_model
from django.db import transaction as db_transaction
from djmoney.money import Money

# Project imports
#
from moneypools.models import BankAccount, Budget, InternalTransaction
from moneypools.service import internal_transaction as internal_transaction_svc
from moneypools.service.funding_strategy import (
    BUDGET_TYPE_TO_STRATEGY,
    EventKind,
)
from moneypools.service.schedules import (
    enumerate_schedule,
    prev_recurrence_boundary,
)

logger = logging.getLogger(__name__)

User = get_user_model()

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
    else:
        scheduling_budget = budget

    account = scheduling_budget.bank_account

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
    tiebreak), and dispatches each event via its budget-type strategy.
    All balance changes flow through internal_transaction_svc so the
    budget-balance invariant is maintained.

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
            if ev.kind == EventKind.FUND:
                Budget.objects.filter(pkid=budget.pkid).update(
                    last_funded_on=ev.date
                )
            else:
                Budget.objects.filter(pkid=budget.pkid).update(
                    last_recurrence_on=ev.date
                )
            continue

        if ev.kind == EventKind.FUND:
            _process_fund_event(ev, account, unallocated, actor, report)
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
    account: BankAccount,
    unallocated: Budget,
    actor: User,  # type: ignore[valid-type]
    report: FundingReport,
) -> None:
    """
    Transfer funds from unallocated into the target budget.

    For Recurring budgets, the target is the fillup_goal.
    Otherwise the target is the budget itself.

    Computes already_moved (existing system fund ITXs for this event date)
    and transfers only the remainder of intended.  Pointer advances
    unconditionally -- under-funded events are not retried on subsequent
    days; same-day re-runs are handled via the already_moved formula.

    Args:
        ev: The funding event to process.
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

    if net <= Decimal("0"):
        Budget.objects.filter(pkid=budget.pkid).update(last_funded_on=ev.date)
        return

    available = unallocated.balance.amount
    if available <= Decimal("0"):
        report.warnings.append(
            f"[{ev.date}] {budget.name}: unallocated is empty; transfer skipped."
        )
        Budget.objects.filter(pkid=budget.pkid).update(last_funded_on=ev.date)
        return

    if net > available:
        report.warnings.append(
            f"[{ev.date}] {budget.name}: wanted {Money(net, intended.currency)}, "
            f"only {unallocated.balance} available; capped."
        )
        net = available

    amount = Money(net, intended.currency)
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
def _process_recur_event(
    ev: FundingEvent,
    account: BankAccount,
    actor: User,  # type: ignore[valid-type]
    report: FundingReport,
) -> None:
    """Transfer from fillup_goal into the recurring budget up to target.

    Computes already_moved (existing system recur ITXs for this event date)
    and transfers only the remainder of intended -- never more.  This makes
    the function safe to call multiple times on the same calendar day:

    - If the fill-up lacked sufficient funds on the first run (partial or
      zero transfer), a subsequent run on the same day will top up the
      remainder provided the fill-up has since been replenished (e.g. the
      user manually moved money into it, or a fund event ran and filled it).
    - If the event was fully satisfied on the first run, already_moved equals
      intended, net is zero, and the second run is a no-op.

    Pointer (last_recurrence_on) and complete flag are written
    unconditionally at the end so the state is consistent regardless of
    whether a transfer occurred.

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

    if net > Decimal("0"):
        fillup_available = fillup.balance.amount
        if fillup_available <= Decimal("0"):
            report.warnings.append(
                f"[{ev.date}] {budget.name}: fill-up goal is empty; transfer skipped."
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

    newly_complete = budget.balance.amount >= budget.target_balance.amount
    Budget.objects.filter(pkid=budget.pkid).update(
        last_recurrence_on=ev.date,
        complete=newly_complete,
    )
