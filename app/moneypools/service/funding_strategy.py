"""
Funding strategy implementations.

Each FundingStrategy subclass computes the "intended amount" for a single
funding or recurrence event, given the current state of the budget (and its
fill-up sibling for Recurring budgets).

Public API:
    EventKind            -- StrEnum: FUND / RECUR
    FundingStrategy      -- abstract base
    GoalStrategy         -- GOAL budgets
    CappedStrategy       -- CAPPED budgets
    RecurringStrategy    -- RECURRING budgets (both event kinds)
    BUDGET_TYPE_TO_STRATEGY -- BudgetType -> FundingStrategy instance
"""

# system imports
#
import enum
import logging
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
from decimal import Decimal

# 3rd party imports
#
import recurrence as recurrence_lib
from djmoney.money import Money

# Project imports
#
from moneypools.models import Budget
from moneypools.service.schedules import (
    count_occurrences,
    enumerate_schedule,
    next_recurrence_boundary,
    prev_recurrence_boundary,
)

logger = logging.getLogger(__name__)


########################################################################
########################################################################
#
class EventKind(enum.StrEnum):
    """Discriminator for the two funding event types."""

    FUND = "fund"
    RECUR = "recur"


########################################################################
########################################################################
#
class FundingStrategy(ABC):
    """Base class for per-budget-type funding amount calculations."""

    @abstractmethod
    def intended_for_event(
        self,
        budget: Budget,
        event_date: date,
        *,
        kind: EventKind,
    ) -> Money:
        """Return the intended transfer amount for this event.

        Does not cap by source balance; the engine applies that cap.

        Args:
            budget: The budget being funded (or whose recur event fires).
            event_date: The scheduled date of this event.
            kind: FUND for a funding event, RECUR for a recurrence event.

        Returns:
            Money amount >= 0.
        """
        ...

    @abstractmethod
    def is_complete(self, budget: Budget) -> bool:
        """Return True if the budget should receive no further fund events.

        Args:
            budget: The Budget to inspect.

        Returns:
            True when the engine should skip this budget's future events.
        """
        ...


########################################################################
########################################################################
#
class GoalStrategy(FundingStrategy):
    """Strategy for GOAL budgets (FIXED_AMOUNT or TARGET_DATE)."""

    ####################################################################
    #
    def intended_for_event(
        self,
        budget: Budget,
        event_date: date,
        *,
        kind: EventKind,
    ) -> Money:
        """Compute intended amount for a Goal fund event.

        FIXED_AMOUNT: returns funding_amount unconditionally (completion
        is tracked via budget.complete, not the amount formula).

        TARGET_DATE: spreads the remaining gap evenly over all schedule
        occurrences from event_date through target_date.

        Args:
            budget: A GOAL budget.
            event_date: The fund event date.
            kind: Always FUND for Goal budgets.

        Returns:
            Money amount >= 0.
        """
        currency = budget.balance.currency
        zero = Money(Decimal("0"), currency)

        if budget.funding_type == Budget.FundingType.FIXED_AMOUNT:
            if budget.funding_amount is None:
                return zero
            return budget.funding_amount

        # TARGET_DATE: divide remaining gap over events left until target.
        gap = budget.target_balance.amount - budget.balance.amount
        if gap <= Decimal("0"):
            return zero

        if budget.target_date is not None:
            remaining = count_occurrences(
                budget.funding_schedule, event_date, budget.target_date
            )
            per_event = (gap / max(remaining, 1)).quantize(Decimal("0.01"))
            return Money(per_event, currency)

        # No target_date: deposit full remaining gap.
        return Money(gap, currency)

    ####################################################################
    #
    def is_complete(self, budget: Budget) -> bool:
        """Return True when the GOAL's complete flag is set."""
        return bool(budget.complete)


########################################################################
########################################################################
#
class CappedStrategy(FundingStrategy):
    """Strategy for CAPPED budgets (FIXED_AMOUNT only)."""

    ####################################################################
    #
    def intended_for_event(
        self,
        budget: Budget,
        event_date: date,
        *,
        kind: EventKind,
    ) -> Money:
        """Compute intended amount for a Capped fund event.

        Returns min(funding_amount, max(0, target_balance - balance)).

        Args:
            budget: A CAPPED budget.
            event_date: The fund event date.
            kind: Always FUND for Capped budgets.

        Returns:
            Money amount >= 0.
        """
        currency = budget.balance.currency
        zero = Money(Decimal("0"), currency)

        if budget.funding_amount is None:
            return zero

        gap = budget.target_balance.amount - budget.balance.amount
        if gap <= Decimal("0"):
            return zero

        return Money(min(budget.funding_amount.amount, gap), currency)

    ####################################################################
    #
    def is_complete(self, budget: Budget) -> bool:
        """Capped budgets are never complete."""
        return False


########################################################################
########################################################################
#
class RecurringStrategy(FundingStrategy):
    """Strategy for RECURRING budgets.

    Handles both fund events (Unallocated -> fill-up) and recur events
    (fill-up -> Recurring).
    """

    ####################################################################
    #
    def intended_for_event(
        self,
        budget: Budget,
        event_date: date,
        *,
        kind: EventKind,
    ) -> Money:
        """Compute intended amount for a Recurring fund or recur event.

        Fund event: prorates the fill-up's remaining gap across all
        funding events in the current recurrence cycle.

        Recur event: returns the gap between the recurring budget's target
        and its current balance (source capping by fill-up balance is done
        by the engine).

        Args:
            budget: A RECURRING budget.
            event_date: The event date.
            kind: FUND or RECUR.

        Returns:
            Money amount >= 0.
        """
        if kind == EventKind.FUND:
            return self._intended_fund(budget, event_date)
        return self._intended_recur(budget, event_date)

    ####################################################################
    #
    def _intended_fund(self, budget: Budget, event_date: date) -> Money:
        """Prorate the fill-up gap over events in the current cycle."""
        fillup = budget.fillup_goal
        if fillup is None:
            return Money(Decimal("0"), budget.balance.currency)

        currency = fillup.balance.currency
        zero = Money(Decimal("0"), currency)

        gap = fillup.target_balance.amount - fillup.balance.amount
        if gap <= Decimal("0"):
            return zero

        if not budget.recurrence_schedule:
            return Money(gap, currency)

        cycle_end = next_recurrence_boundary(
            budget.recurrence_schedule, event_date + timedelta(days=1)
        )
        if cycle_end is None:
            return Money(gap, currency)

        _prev = prev_recurrence_boundary(budget.recurrence_schedule, event_date)
        cycle_start = (
            _prev or budget.last_recurrence_on or budget.created_at.date()
        )

        if _prev is None and budget.last_recurrence_on is None:
            # First cycle: project the theoretical prior boundary backward
            # using cycle_end's month/day as an anchor.  Without this, N
            # counts only remaining events rather than the full cycle,
            # inflating the per-event amount.
            early_anchor = datetime(
                cycle_end.year - 3, cycle_end.month, cycle_end.day
            )
            one_before = cycle_end - timedelta(days=1)
            end_search = datetime(
                one_before.year, one_before.month, one_before.day, 23, 59, 59
            )
            try:
                prior_occs = list(
                    budget.recurrence_schedule.between(
                        early_anchor, end_search, inc=True, dtstart=early_anchor
                    )
                )
                if prior_occs:
                    last_occ = prior_occs[-1]
                    theoretical_start = (
                        last_occ.date()
                        if hasattr(last_occ, "date")
                        else date(last_occ.year, last_occ.month, last_occ.day)
                    )
                    cycle_start = theoretical_start
            except (recurrence_lib.RecurrenceError, TypeError, ValueError):
                pass

        if cycle_start >= cycle_end:
            # event_date falls before the first recurrence boundary (e.g. a
            # catch-up funding event on Apr 30 with DTSTART May 1).  Use the
            # first full cycle's event count as the rate basis.
            look_ahead = date(
                cycle_end.year + 2, cycle_end.month, cycle_end.day
            )
            future = enumerate_schedule(
                budget.recurrence_schedule, cycle_end, look_ahead
            )
            if future:
                next_cycle_end = future[0]
                return _fill_amount_prorated(
                    budget,
                    fillup,
                    event_date,
                    cycle_end - timedelta(days=1),
                    next_cycle_end - timedelta(days=1),
                )

        return _fill_amount_prorated(
            budget,
            fillup,
            event_date,
            cycle_start,
            cycle_end - timedelta(days=1),
        )

    ####################################################################
    #
    def _intended_recur(self, budget: Budget, event_date: date) -> Money:
        """Return the gap between the recurring budget's target and balance."""
        currency = budget.balance.currency
        gap = budget.target_balance.amount - budget.balance.amount
        if gap <= Decimal("0"):
            return Money(Decimal("0"), currency)
        return Money(gap, currency)

    ####################################################################
    #
    def is_complete(self, budget: Budget) -> bool:
        """Recurring budgets use the complete flag only within-cycle."""
        return False


########################################################################
########################################################################
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
    target balance per event, capped at the remaining gap.

    Args:
        budget: Budget whose funding_schedule defines the event cadence.
        target: Budget being funded (fill-up goal for Recurring).
        event_date: The funding event date (kept for API compatibility).
        cycle_start: Exclusive lower bound for counting events in the cycle.
        cycle_before: Inclusive upper bound for counting events in the cycle.

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
    # Use the earlier of DTSTART and cycle_start so that prior-cycle events
    # are counted even when DTSTART is later than the theoretical start.
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


########################################################################
########################################################################
#
BUDGET_TYPE_TO_STRATEGY: dict[str, FundingStrategy] = {
    Budget.BudgetType.GOAL: GoalStrategy(),
    Budget.BudgetType.CAPPED: CappedStrategy(),
    Budget.BudgetType.RECURRING: RecurringStrategy(),
}
