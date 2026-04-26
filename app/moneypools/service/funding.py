"""
Budget funding engine -- Phase 6.

Entry point:
    fund_account(account, today, actor) -> FundingReport

The engine processes two event types per budget:

  Fund events   -- fire on budget.funding_schedule.
                   Transfer money from the account's unallocated budget
                   into the target budget (or its fillup_goal for
                   recurring-with-fillup budgets).

  Recur events  -- fire on budget.recurrance_schedule.
                   Only for Recurring + with_fillup_goal budgets.
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
from datetime import date, datetime, timedelta
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
            continue

        if ev.kind == _KIND_FUND:
            _process_fund_event(ev, account, unallocated, actor, report, today)
        else:
            _process_recur_event(ev, account, actor, report)

    return report


########################################################################
########################################################################
#
def _collect_events(budgets: list[Budget], today: date) -> list[FundingEvent]:
    """Enumerate all due funding and recurrence events for a set of budgets.

    Args:
        budgets: Budgets to inspect (already filtered to non-archived).
        today: Upper bound (inclusive) for event enumeration.

    Returns:
        Unsorted list of FundingEvent objects.
    """
    events: list[FundingEvent] = []

    for budget in budgets:
        # Fill-up goal children are funded indirectly via their parent's
        # fund events; they do not generate their own events.
        if budget.budget_type == Budget.BudgetType.ASSOCIATED_FILLUP_GOAL:
            continue

        # Complete Goals are sticky -- never re-funded.
        if budget.budget_type == Budget.BudgetType.GOAL and budget.complete:
            continue

        after = budget.last_funded_on or budget.created_at.date()
        for d in _enumerate_schedule(budget.funding_schedule, after, today):
            events.append(FundingEvent(date=d, kind=_KIND_FUND, budget=budget))

        if (
            budget.budget_type == Budget.BudgetType.RECURRING
            and budget.with_fillup_goal
            and budget.fillup_goal is not None
            and budget.recurrance_schedule
        ):
            recur_after = budget.last_recurrence_on or budget.created_at.date()
            for d in _enumerate_schedule(
                budget.recurrance_schedule, recur_after, today
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
    """Transfer funds from unallocated into the target budget.

    For Recurring + with_fillup_goal, the target is the fillup_goal.
    Otherwise the target is the budget itself.  Caps at unallocated
    balance, advances last_funded_on regardless.

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
            and budget.with_fillup_goal
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
            f"[{ev.date}] {budget.name}: unallocated is empty; skipped."
        )
        Budget.objects.filter(pkid=budget.pkid).update(last_funded_on=ev.date)
        return

    if amount.amount > available:
        report.warnings.append(
            f"[{ev.date}] {budget.name}: wanted {amount}, "
            f"only {unallocated.balance} available; capped."
        )
        amount = Money(available, amount.currency)

    with db_transaction.atomic():
        internal_transaction_svc.create(
            bank_account=account,
            src_budget=unallocated,
            dst_budget=target,
            amount=amount,
            actor=actor,
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

    # TARGET_DATE: spread the remaining gap over remaining occurrences.
    gap = target.target_balance.amount - target.balance.amount
    if gap <= Decimal("0"):
        return zero

    remaining = _count_remaining_occurrences(
        budget.funding_schedule,
        event_date,
        budget.target_date or today,
    )
    per_event = (gap / max(remaining, 1)).quantize(Decimal("0.01"))
    return Money(per_event, currency)


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
            f"[{ev.date}] {budget.name}: fill-up goal is empty; "
            "recurring budget underfunded."
        )
        Budget.objects.filter(pkid=budget.pkid).update(
            last_recurrence_on=ev.date
        )
        return

    transfer = min(gap, fillup_available)
    if transfer < gap:
        report.warnings.append(
            f"[{ev.date}] {budget.name}: fill-up only had "
            f"{fillup.balance}; needed {gap}; underfunded."
        )

    amount = Money(transfer, budget.balance.currency)

    with db_transaction.atomic():
        internal_transaction_svc.create(
            bank_account=account,
            src_budget=fillup,
            dst_budget=budget,
            amount=amount,
            actor=actor,
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
