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
    state_at_start_of_D  -- roll back system ITXs to get state at start of D
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
from django.db.models import Q
from djmoney.money import Money

# Project imports
#
from moneypools.models import Budget, InternalTransaction
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
def state_at_start_of_D(
    budget: Budget,
    D: date,
) -> tuple[Money, Money]:
    """Return (balance, funded_amount) for budget as of the start of date D.

    Rolls back all system-issued InternalTransactions touching budget with
    system_event_date >= D.  System-issued ITXs are identified by having a
    non-null system_event_date.

    The filter uses >= rather than == so that a multi-day catch-up run
    (processing missed days in order) sees the correct pre-event state for
    each day.  Without >=, when processing day D+1 after D has already been
    applied, intended_for_(D+1) would see D's transfer already in the
    balance and compute a smaller gap than it should.

    For same-day re-runs this also rolls back ITXs issued for D on a prior
    run, so intended_for_D is computed against the same pre-event baseline
    every time.  The already_moved formula then determines how much of that
    intended amount is still outstanding.

    Args:
        budget: The Budget to compute state for.
        D: The event date to roll back to the start of.

    Returns:
        Tuple of (balance_at_start_of_D, funded_amount_at_start_of_D).
    """
    system_itxs = InternalTransaction.objects.filter(
        system_event_date__isnull=False,
        system_event_date__gte=D,
    ).filter(Q(src_budget=budget) | Q(dst_budget=budget))

    # signed_amount(X) = +amount if dst_budget==X, -amount if src_budget==X
    # B_0 = current_balance - sum(signed_amount) over S(X, D)
    net_signed = Decimal("0")
    for itx in system_itxs:
        if itx.dst_budget_id == budget.id:
            net_signed += itx.amount.amount
        else:
            net_signed -= itx.amount.amount

    currency = budget.balance.currency
    balance_0 = Money(budget.balance.amount - net_signed, currency)
    funded_amount_0 = Money(budget.funded_amount.amount - net_signed, currency)
    return balance_0, funded_amount_0


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

        Gap calculations use funded_amount_0 (from state_at_start_of_D),
        not the current balance.  The distinction matters because spending
        debits the balance via TransactionAllocations but does not affect
        funded_amount -- only InternalTransactions move funded_amount.
        Using balance would treat spending as if it were unfunded gap and
        over-fund the budget.

        Example: a $300 vacation Goal funded $200 so far.  The user then
        books a $50 flight, leaving balance at $150.  The remaining funding
        gap is $100 (300 - 200), not $150 (300 - 150).  The $50 spend is
        already committed; we only need to fund the $100 that was never
        deposited.

        FIXED_AMOUNT: returns min(funding_amount, gap) so the engine never
        exceeds the target.  Completion is latched in
        internal_transaction_svc, not here -- this function returns 0 once
        funded_amount_0 >= target, which stops further events before the
        latch check is even needed.

        TARGET_DATE: spreads the remaining gap evenly over all schedule
        occurrences from event_date through target_date (minimum 1).
        After the deadline passes, count_occurrences returns 1 so the
        full remaining gap is closed on the next event.

        Args:
            budget: A GOAL budget.
            event_date: The fund event date.
            kind: Always FUND for Goal budgets.

        Returns:
            Money amount >= 0.
        """
        currency = budget.balance.currency
        zero = Money(Decimal("0"), currency)

        _, funded_amount_0 = state_at_start_of_D(budget, event_date)
        gap = budget.target_balance.amount - funded_amount_0.amount
        if gap <= Decimal("0"):
            return zero

        if budget.funding_type == Budget.FundingType.FIXED_AMOUNT:
            if budget.funding_amount is None:
                return zero
            return Money(min(budget.funding_amount.amount, gap), currency)

        # TARGET_DATE: divide remaining gap over events left until target.
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

        balance_0, _ = state_at_start_of_D(budget, event_date)
        gap = budget.target_balance.amount - balance_0.amount
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
        """Prorate the fill-up gap over the funding events in the current cycle.

        Money flows Unallocated -> fill-up, not directly into the Recurring
        budget.  The fill-up accumulates across funding events until the
        recur event sweeps it into the Recurring on the cycle boundary.

        The per-event amount is target_balance / N, where N is the number
        of funding events in the current recurrence cycle (from the last
        recur boundary, exclusive, through the next recur boundary,
        inclusive).  This spreads the cost evenly rather than depositing
        the full target on the first event of each cycle.

        Example: a $600/month Recurring budget funded weekly (4 events per
        cycle).  Each fund event contributes $150 to the fill-up.  On the
        1st of the month the recur event sweeps $600 from the fill-up into
        the Recurring.

        The first-cycle case is special: when no recurrence has ever fired
        (last_recurrence_on is None and no prior boundary exists), the
        theoretical prior boundary is projected backward from cycle_end to
        find the correct N for a full cycle rather than counting only the
        remaining events, which would inflate the per-event amount.

        Args:
            budget: A RECURRING budget.
            event_date: The fund event date.

        Returns:
            Money amount >= 0.
        """
        fillup = budget.fillup_goal
        if fillup is None:
            return Money(Decimal("0"), budget.balance.currency)

        currency = fillup.balance.currency
        zero = Money(Decimal("0"), currency)

        fill_balance_0, _ = state_at_start_of_D(fillup, event_date)
        gap = fillup.target_balance.amount - fill_balance_0.amount
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
        """Return the gap between the Recurring budget's target and its B_0.

        Uses balance_0 (rolled back via state_at_start_of_D) rather than
        current balance so that a same-day re-run or catch-up run sees the
        pre-event state for this cycle boundary.

        Example: a Recurring budget has target $600 and balance $0 at the
        start of the recur date.  The fill-up has $500.  The first run
        transfers $500 (capped by fill-up balance), leaving the Recurring
        at $500.  On a re-run after the fill-up is topped up, B_0 is still
        $0 (the recur ITX is rolled back), so intended is still $600.
        already_moved is $500, net is $100 -- exactly the remainder needed.

        Args:
            budget: A RECURRING budget.
            event_date: The recur event date.

        Returns:
            Money amount >= 0.
        """
        currency = budget.balance.currency
        balance_0, _ = state_at_start_of_D(budget, event_date)
        gap = budget.target_balance.amount - balance_0.amount
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
    """Compute the per-event deposit toward a budget's target for one event.

    Counts N, the remaining funding events from event_date (inclusive)
    through cycle_before (inclusive), then returns full_gap / N.

    Dividing the current gap by remaining events -- not target_balance by
    total cycle events -- ensures an even spread regardless of carry-over.

    Example: $600/month target, 3 funding events in the cycle (1st, 15th,
    and the recur boundary on the 1st of next month), fill-up already
    holds $100 from the previous cycle.  full_gap = $500.

    - Event on the 1st:  N=3, per_event = $500/3 = $166.67
    - Event on the 15th: N=2, fill_B_0 = $266.67, gap = $333.33,
                         per_event = $333.33/2 = $166.67
    - Event on the recur boundary: N=1, gap = $166.66, per_event = $166.66

    Total deposited = $500 -- exactly the gap, deposited evenly.

    If the simpler target/total-N formula were used, events would deposit
    $200/$200/$100 -- correct in total but uneven, and wrong when the
    carry-over changes mid-cycle.

    effective_dtstart is clamped to min(DTSTART, event_date - 1 day) so
    that the recurrence library counts from the right anchor even when
    DTSTART is set later than the current event.

    Args:
        budget: Budget whose funding_schedule defines the event cadence.
        target: Budget being funded (fill-up goal for Recurring).
        event_date: The funding event date; used as the lower bound for
            counting remaining events and for state_at_start_of_D.
        cycle_start: Unused; kept for call-site compatibility.
        cycle_before: Inclusive upper bound for counting remaining events.

    Returns:
        Money amount to transfer, >= 0.
    """
    currency = target.balance.currency
    zero = Money(Decimal("0"), currency)

    fill_balance_0, _ = state_at_start_of_D(target, event_date)
    full_gap = target.target_balance.amount - fill_balance_0.amount
    if full_gap <= Decimal("0"):
        return zero

    sched = budget.funding_schedule
    if not sched:
        return Money(full_gap, currency)

    # Count remaining events in [event_date, cycle_before].
    # between() is exclusive on the lower bound, so subtract one day.
    after_dt = datetime(
        event_date.year, event_date.month, event_date.day
    ) - timedelta(days=1)
    before_dt = datetime(
        cycle_before.year, cycle_before.month, cycle_before.day, 23, 59, 59
    )

    raw = sched.dtstart
    raw_clean = raw.replace(tzinfo=None) if raw is not None else None
    # Clamp dtstart to after_dt so events on or after event_date are
    # counted even when the stored DTSTART is later.
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
        if event_date <= d <= cycle_before:
            results.append(d)

    N = len(sorted(set(results)))
    if N == 0:
        return Money(full_gap, currency)

    per_event = (full_gap / Decimal(N)).quantize(Decimal("0.01"))
    return Money(per_event, currency)


########################################################################
########################################################################
#
BUDGET_TYPE_TO_STRATEGY: dict[str, FundingStrategy] = {
    Budget.BudgetType.GOAL: GoalStrategy(),
    Budget.BudgetType.CAPPED: CappedStrategy(),
    Budget.BudgetType.RECURRING: RecurringStrategy(),
}
