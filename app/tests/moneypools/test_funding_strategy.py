#!/usr/bin/env python
#
"""
Tests for funding_strategy.py (strategy dispatch) and the
state_at_start_of_D helper in funding.py.
"""

# system imports
#
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

# 3rd party imports
#
import pytest
import recurrence
from django.conf import settings
from django.contrib.auth import get_user_model
from djmoney.money import Money

# Project imports
#
from moneypools.models import BankAccount, Budget, InternalTransaction
from moneypools.service import budget as budget_svc
from moneypools.service import internal_transaction as internal_transaction_svc
from moneypools.service.funding_strategy import (
    BUDGET_TYPE_TO_STRATEGY,
    CappedStrategy,
    EventKind,
    GoalStrategy,
    RecurringStrategy,
    state_at_start_of_D,
)

User = get_user_model()

pytestmark = pytest.mark.django_db

# Fires on the 1st of each month.
_MONTHLY = recurrence.Recurrence(
    dtstart=datetime(2026, 1, 1),
    rrules=[recurrence.Rule(recurrence.MONTHLY)],
)

# Fires on the 10th and 20th of each month -- two events per monthly cycle.
_TWICE_MONTHLY = recurrence.Recurrence(
    dtstart=datetime(2026, 2, 10),
    rrules=[recurrence.Rule(recurrence.MONTHLY, bymonthday=[10, 20])],
)

# Recurrence reset on the 1st of each month.
_MONTHLY_FIRST = recurrence.Recurrence(
    dtstart=datetime(2026, 2, 1),
    rrules=[recurrence.Rule(recurrence.MONTHLY)],
)


####################################################################
#
@pytest.fixture
def system_user() -> User:  # type: ignore[valid-type]
    """Return the funding-system user seeded by migration 0024."""
    return User.objects.get(username=settings.FUNDING_SYSTEM_USERNAME)


####################################################################
#
@pytest.fixture
def make_account(
    bank_account_factory: Callable[..., BankAccount],
) -> Callable[..., BankAccount]:
    """Return a factory for BankAccounts with optional last_posted_through."""

    def _make(posted_through: date | None = None) -> BankAccount:
        return bank_account_factory(last_posted_through=posted_through)

    return _make


########################################################################
########################################################################
#
class TestGoalStrategy:
    """Unit tests for GoalStrategy.intended_for_event and is_complete."""

    ####################################################################
    #
    def test_fixed_amount_returns_funding_amount(
        self,
        make_account: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: a Goal budget configured to transfer $50 per fund event
        WHEN:  the strategy computes the intended amount for a fund event
        THEN:  returns $50 regardless of the current balance
        """
        account = make_account()
        budget = budget_svc.create(
            bank_account=account,
            name="Shoes",
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(300, "USD"),
            funding_amount=Money(50, "USD"),
            funding_schedule=_MONTHLY,
        )
        Budget.objects.filter(pkid=budget.pkid).update(
            balance=Money(100, "USD")
        )
        budget.refresh_from_db()

        result = GoalStrategy().intended_for_event(
            budget, date(2026, 3, 1), kind=EventKind.FUND
        )

        assert result == Money(50, "USD")

    ####################################################################
    #
    def test_fixed_amount_none_returns_zero(
        self,
        make_account: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: a Goal budget with no funding amount configured
        WHEN:  the strategy computes the intended amount
        THEN:  returns $0
        """
        account = make_account()
        budget = budget_svc.create(
            bank_account=account,
            name="Mystery Goal",
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(100, "USD"),
            funding_schedule=_MONTHLY,
        )
        Budget.objects.filter(pkid=budget.pkid).update(funding_amount=None)
        budget.refresh_from_db()

        result = GoalStrategy().intended_for_event(
            budget, date(2026, 3, 1), kind=EventKind.FUND
        )

        assert result == Money(0, "USD")

    ####################################################################
    #
    def test_target_date_spreads_gap_over_remaining_events(
        self,
        make_account: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: a Goal budget with $300 still needed and three monthly fund events
               remaining before the target date (January, February, March)
        WHEN:  the strategy computes the intended amount for the January event
        THEN:  returns $100, spreading the gap evenly across the three events
        """
        account = make_account()
        budget = budget_svc.create(
            bank_account=account,
            name="Vacation",
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.TARGET_DATE,
            target_balance=Money(300, "USD"),
            target_date=date(2026, 3, 1),
            funding_schedule=_MONTHLY,
        )

        result = GoalStrategy().intended_for_event(
            budget, date(2026, 1, 1), kind=EventKind.FUND
        )

        # 3 occurrences Jan 1, Feb 1, Mar 1 → $300 / 3 = $100
        assert result == Money(100, "USD")

    ####################################################################
    #
    def test_target_date_past_deadline_returns_full_gap(
        self,
        make_account: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: a Goal budget whose target date has already passed with $40 funded out of $100
        WHEN:  the strategy computes the intended amount for a fund event after the deadline
        THEN:  returns the full $60 remaining gap (target minus funded_amount) in one event
        """
        account = make_account()
        budget = budget_svc.create(
            bank_account=account,
            name="Late Vacation",
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.TARGET_DATE,
            target_balance=Money(100, "USD"),
            target_date=date(2026, 1, 1),
            funding_schedule=_MONTHLY,
        )
        Budget.objects.filter(pkid=budget.pkid).update(
            balance=Money(40, "USD"),
            funded_amount=Money(40, "USD"),
        )
        budget.refresh_from_db()

        # Event date after target_date: count_occurrences returns 1 (the floor)
        # so the full remaining gap is returned.
        result = GoalStrategy().intended_for_event(
            budget, date(2026, 3, 1), kind=EventKind.FUND
        )

        assert result == Money(60, "USD")

    ####################################################################
    #
    @pytest.mark.parametrize(
        "complete,expected",
        [(True, True), (False, False)],
    )
    def test_is_complete_mirrors_complete_flag(
        self,
        make_account: Callable[..., BankAccount],
        complete: bool,
        expected: bool,
    ) -> None:
        """
        GIVEN: a Goal budget whose complete flag is True or False (parametrized)
        WHEN:  is_complete is called
        THEN:  returns exactly the value of the complete flag
        """
        account = make_account()
        budget = budget_svc.create(
            bank_account=account,
            name="Gadget",
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(100, "USD"),
            funding_amount=Money(25, "USD"),
            funding_schedule=_MONTHLY,
        )
        Budget.objects.filter(pkid=budget.pkid).update(complete=complete)
        budget.refresh_from_db()

        assert GoalStrategy().is_complete(budget) is expected


########################################################################
########################################################################
#
class TestGoalCompletionLatch:
    """Tests for the sticky completion latch on Goal budgets."""

    ####################################################################
    #
    def test_latch_fires_at_threshold_and_stays_set(
        self,
        make_account: Callable[..., BankAccount],
        system_user: User,  # type: ignore[valid-type]
    ) -> None:
        """
        GIVEN: a Goal budget with target $100 and an Unallocated source budget
        WHEN:  a credit brings funded_amount to exactly $100
        THEN:  complete flips to True; a second credit keeps complete=True
               and funded_amount continues to grow; deleting the first credit
               reverses funded_amount but leaves complete=True (high-water mark)
        """
        account = make_account()
        unallocated = Budget.objects.get(
            bank_account=account, name="Unallocated"
        )
        Budget.objects.filter(pkid=unallocated.pkid).update(
            balance=Money(300, "USD")
        )
        unallocated.refresh_from_db()

        goal = budget_svc.create(
            bank_account=account,
            name="Laptop",
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(100, "USD"),
            funding_amount=Money(60, "USD"),
            funding_schedule=_MONTHLY,
        )

        # First credit: $60 -- below threshold, latch should NOT fire.
        internal_transaction_svc.create(
            bank_account=account,
            src_budget=unallocated,
            dst_budget=goal,
            amount=Money(60, "USD"),
            actor=system_user,
        )
        goal.refresh_from_db()
        assert goal.funded_amount == Money(60, "USD")
        assert goal.complete is False

        # Second credit: $40 -- brings funded_amount to exactly $100 (threshold).
        itx2 = internal_transaction_svc.create(
            bank_account=account,
            src_budget=unallocated,
            dst_budget=goal,
            amount=Money(40, "USD"),
            actor=system_user,
        )
        goal.refresh_from_db()
        assert goal.funded_amount == Money(100, "USD")
        assert goal.complete is True

        # Third credit: $10 -- funded_amount rises above target; complete stays True.
        internal_transaction_svc.create(
            bank_account=account,
            src_budget=unallocated,
            dst_budget=goal,
            amount=Money(10, "USD"),
            actor=system_user,
        )
        goal.refresh_from_db()
        assert goal.funded_amount == Money(110, "USD")
        assert goal.complete is True

        # Delete the threshold-crossing credit (itx2); funded_amount drops back.
        # complete must NOT be cleared -- it is a high-water mark.
        internal_transaction_svc.delete(itx2)
        goal.refresh_from_db()
        assert goal.funded_amount == Money(70, "USD")
        assert goal.complete is True


########################################################################
########################################################################
#
class TestCappedStrategy:
    """Unit tests for CappedStrategy.intended_for_event and is_complete."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "balance,funding_amount,target,expected",
        [
            # Normal: funding_amount < gap → return funding_amount
            (Decimal("10"), Decimal("20"), Decimal("50"), Decimal("20")),
            # Cap: funding_amount > gap → return gap
            (Decimal("40"), Decimal("20"), Decimal("50"), Decimal("10")),
        ],
    )
    def test_returns_min_of_funding_amount_and_gap(
        self,
        make_account: Callable[..., BankAccount],
        balance: Decimal,
        funding_amount: Decimal,
        target: Decimal,
        expected: Decimal,
    ) -> None:
        """
        GIVEN: a Capped budget at a given balance with a fixed funding amount (parametrized)
        WHEN:  the strategy computes the intended amount
        THEN:  returns whichever is smaller -- the configured funding amount or the remaining gap to target
        """
        account = make_account()
        budget = budget_svc.create(
            bank_account=account,
            name="Emergency Fund",
            budget_type=Budget.BudgetType.CAPPED,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(target, "USD"),
            funding_amount=Money(funding_amount, "USD"),
            funding_schedule=_MONTHLY,
        )
        Budget.objects.filter(pkid=budget.pkid).update(
            balance=Money(balance, "USD")
        )
        budget.refresh_from_db()

        result = CappedStrategy().intended_for_event(
            budget, date(2026, 3, 1), kind=EventKind.FUND
        )

        assert result == Money(expected, "USD")

    ####################################################################
    #
    def test_returns_zero_when_at_or_above_target(
        self,
        make_account: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: a Capped budget whose balance already equals its target
        WHEN:  the strategy computes the intended amount
        THEN:  returns $0 because the budget is already full
        """
        account = make_account()
        budget = budget_svc.create(
            bank_account=account,
            name="Topped-Up Fund",
            budget_type=Budget.BudgetType.CAPPED,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(50, "USD"),
            funding_amount=Money(20, "USD"),
            funding_schedule=_MONTHLY,
        )
        Budget.objects.filter(pkid=budget.pkid).update(balance=Money(50, "USD"))
        budget.refresh_from_db()

        result = CappedStrategy().intended_for_event(
            budget, date(2026, 3, 1), kind=EventKind.FUND
        )

        assert result == Money(0, "USD")

    ####################################################################
    #
    def test_is_complete_always_false(
        self,
        make_account: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: a Capped budget at full balance
        WHEN:  is_complete is called
        THEN:  returns False because Capped budgets are never marked complete
        """
        account = make_account()
        budget = budget_svc.create(
            bank_account=account,
            name="Always On",
            budget_type=Budget.BudgetType.CAPPED,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(100, "USD"),
            funding_amount=Money(20, "USD"),
            funding_schedule=_MONTHLY,
        )
        Budget.objects.filter(pkid=budget.pkid).update(
            balance=Money(100, "USD")
        )
        budget.refresh_from_db()

        assert CappedStrategy().is_complete(budget) is False


########################################################################
########################################################################
#
class TestRecurringStrategy:
    """Unit tests for RecurringStrategy.intended_for_event and is_complete."""

    ####################################################################
    #
    def test_fund_event_prorates_fillup_gap(
        self,
        make_account: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: a Recurring budget whose fill-up has $80 still needed,
               with two fund events (Feb 10 and Feb 20) remaining before the March 1 recur date
        WHEN:  the strategy computes the intended fund-event amount for Feb 10
        THEN:  returns $40, splitting the fill-up gap evenly across the two remaining events
        """
        today = date(2026, 2, 10)
        account = make_account()
        recurring = budget_svc.create(
            bank_account=account,
            name="Monthly Bills",
            budget_type=Budget.BudgetType.RECURRING,
            funding_type=Budget.FundingType.TARGET_DATE,
            target_balance=Money(80, "USD"),
            funding_schedule=_TWICE_MONTHLY,
            recurrence_schedule=_MONTHLY_FIRST,
        )
        recurring.refresh_from_db()
        fillup = recurring.fillup_goal
        assert fillup is not None
        # Fill-up starts at 0 (full gap = $80)
        Budget.objects.filter(pkid=recurring.pkid).update(
            last_funded_on=date(2026, 2, 9),
            last_recurrence_on=date(2026, 2, 1),
        )
        recurring.refresh_from_db()
        fillup.refresh_from_db()

        result = RecurringStrategy().intended_for_event(
            recurring, today, kind=EventKind.FUND
        )

        # 2 fund events in the cycle (Feb 10, Feb 20): $80 / 2 = $40
        assert result == Money(40, "USD")

    ####################################################################
    #
    def test_recur_event_returns_gap(
        self,
        make_account: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: a Recurring budget with a $30 balance against a $100 target
        WHEN:  the strategy computes the intended recur-event amount
        THEN:  returns $70, the full gap; the engine will cap this against the fill-up balance
        """
        account = make_account()
        recurring = budget_svc.create(
            bank_account=account,
            name="Monthly Bills",
            budget_type=Budget.BudgetType.RECURRING,
            funding_type=Budget.FundingType.TARGET_DATE,
            target_balance=Money(100, "USD"),
            funding_schedule=_MONTHLY,
            recurrence_schedule=_MONTHLY,
        )
        Budget.objects.filter(pkid=recurring.pkid).update(
            balance=Money(30, "USD")
        )
        recurring.refresh_from_db()

        result = RecurringStrategy().intended_for_event(
            recurring, date(2026, 3, 1), kind=EventKind.RECUR
        )

        assert result == Money(70, "USD")

    ####################################################################
    #
    def test_recur_event_returns_zero_when_at_target(
        self,
        make_account: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: a Recurring budget whose balance already equals its target
        WHEN:  the strategy computes the intended recur-event amount
        THEN:  returns $0 because there is no gap to fill
        """
        account = make_account()
        recurring = budget_svc.create(
            bank_account=account,
            name="Monthly Bills",
            budget_type=Budget.BudgetType.RECURRING,
            funding_type=Budget.FundingType.TARGET_DATE,
            target_balance=Money(100, "USD"),
            funding_schedule=_MONTHLY,
            recurrence_schedule=_MONTHLY,
        )
        Budget.objects.filter(pkid=recurring.pkid).update(
            balance=Money(100, "USD")
        )
        recurring.refresh_from_db()

        result = RecurringStrategy().intended_for_event(
            recurring, date(2026, 3, 1), kind=EventKind.RECUR
        )

        assert result == Money(0, "USD")

    ####################################################################
    #
    def test_is_complete_always_false(
        self,
        make_account: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: a Recurring budget
        WHEN:  is_complete is called
        THEN:  returns False because the Recurring strategy never reports completion
        """
        account = make_account()
        recurring = budget_svc.create(
            bank_account=account,
            name="Monthly Bills",
            budget_type=Budget.BudgetType.RECURRING,
            funding_type=Budget.FundingType.TARGET_DATE,
            target_balance=Money(100, "USD"),
            funding_schedule=_MONTHLY,
            recurrence_schedule=_MONTHLY,
        )

        assert RecurringStrategy().is_complete(recurring) is False


########################################################################
########################################################################
#
class TestBudgetTypeToStrategyRegistry:
    """Verify BUDGET_TYPE_TO_STRATEGY covers the three dispatchable types."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "budget_type,expected_class",
        [
            (Budget.BudgetType.GOAL, GoalStrategy),
            (Budget.BudgetType.CAPPED, CappedStrategy),
            (Budget.BudgetType.RECURRING, RecurringStrategy),
        ],
    )
    def test_registry_maps_type_to_correct_strategy(
        self,
        budget_type: str,
        expected_class: type,
    ) -> None:
        """
        GIVEN: the BUDGET_TYPE_TO_STRATEGY registry
        WHEN:  a budget type is looked up (parametrized over Goal, Capped, and Recurring)
        THEN:  the returned object is an instance of the expected strategy class
        """
        assert isinstance(BUDGET_TYPE_TO_STRATEGY[budget_type], expected_class)

    ####################################################################
    #
    def test_associated_fillup_goal_not_in_registry(self) -> None:
        """
        GIVEN: the BUDGET_TYPE_TO_STRATEGY registry
        WHEN:  Associated Fill-up Goal is looked up
        THEN:  raises KeyError because the engine dispatches to fill-up children only
               via their Recurring parent, never directly
        """
        with pytest.raises(KeyError):
            _ = BUDGET_TYPE_TO_STRATEGY[
                Budget.BudgetType.ASSOCIATED_FILLUP_GOAL
            ]


########################################################################
########################################################################
#
class TestStateAtStartOfD:
    """Regression tests for state_at_start_of_D rollback arithmetic."""

    ####################################################################
    #
    def test_no_system_itxs_returns_current_state(
        self,
        make_account: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: a budget with a $100 balance and no system-issued transfers on or after the query date
        WHEN:  state_at_start_of_D is called
        THEN:  returns the current balance unchanged because there is nothing to roll back
        """
        today = date(2026, 3, 1)
        account = make_account(posted_through=today)
        unallocated = account.unallocated_budget
        assert unallocated is not None
        budget = budget_svc.create(
            bank_account=account,
            name="Test Goal",
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(200, "USD"),
            funding_amount=Money(50, "USD"),
            funding_schedule=_MONTHLY,
        )
        Budget.objects.filter(pkid=budget.pkid).update(
            balance=Money(100, "USD")
        )
        budget.refresh_from_db()

        balance_0, _ = state_at_start_of_D(budget, today)

        assert balance_0 == Money(100, "USD")

    ####################################################################
    #
    def test_rolls_back_credit_on_date_D(
        self,
        make_account: Callable[..., BankAccount],
        system_user: User,  # type: ignore[valid-type]
    ) -> None:
        """
        GIVEN: a budget that received a $20 system-issued credit on March 1, leaving a current balance of $20
        WHEN:  state_at_start_of_D is called for March 1
        THEN:  returns $0 because the credit on that date is rolled back
        """
        today = date(2026, 3, 1)
        account = make_account(posted_through=today)
        unallocated = account.unallocated_budget
        assert unallocated is not None
        Budget.objects.filter(pkid=unallocated.pkid).update(
            balance=Money(200, "USD")
        )
        budget = budget_svc.create(
            bank_account=account,
            name="Test Goal",
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(200, "USD"),
            funding_amount=Money(20, "USD"),
            funding_schedule=_MONTHLY,
        )

        # Simulate a system ITX that credited $20 to budget on D.
        effective_dt = datetime(today.year, today.month, today.day, tzinfo=UTC)
        itx = internal_transaction_svc.create(
            bank_account=account,
            src_budget=unallocated,
            dst_budget=budget,
            amount=Money(20, "USD"),
            actor=system_user,
            effective_date=effective_dt,
        )
        InternalTransaction.objects.filter(pk=itx.pk).update(
            system_event_date=today
        )

        budget.refresh_from_db()
        assert budget.balance == Money(20, "USD")

        balance_0, _ = state_at_start_of_D(budget, today)

        assert balance_0 == Money(0, "USD")

    ####################################################################
    #
    def test_does_not_roll_back_itx_before_D(
        self,
        make_account: Callable[..., BankAccount],
        system_user: User,  # type: ignore[valid-type]
    ) -> None:
        """
        GIVEN: a budget that received a $20 system-issued credit on February 28, leaving a current balance of $20,
               and the query date is March 1
        WHEN:  state_at_start_of_D is called for March 1
        THEN:  returns $20 unchanged because credits dated before the query date are not rolled back
        """
        D = date(2026, 3, 1)
        account = make_account(posted_through=D)
        unallocated = account.unallocated_budget
        assert unallocated is not None
        Budget.objects.filter(pkid=unallocated.pkid).update(
            balance=Money(200, "USD")
        )
        budget = budget_svc.create(
            bank_account=account,
            name="Test Goal",
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(200, "USD"),
            funding_amount=Money(20, "USD"),
            funding_schedule=_MONTHLY,
        )

        effective_dt = datetime(
            (D - timedelta(days=1)).year,
            (D - timedelta(days=1)).month,
            (D - timedelta(days=1)).day,
            tzinfo=UTC,
        )
        itx = internal_transaction_svc.create(
            bank_account=account,
            src_budget=unallocated,
            dst_budget=budget,
            amount=Money(20, "USD"),
            actor=system_user,
            effective_date=effective_dt,
        )
        InternalTransaction.objects.filter(pk=itx.pk).update(
            system_event_date=D - timedelta(days=1)
        )

        budget.refresh_from_db()
        assert budget.balance == Money(20, "USD")

        balance_0, _ = state_at_start_of_D(budget, D)

        # D-1 ITX is not rolled back; balance_0 equals current balance.
        assert balance_0 == Money(20, "USD")

    ####################################################################
    #
    @pytest.mark.parametrize(
        "query_date,expected_balance",
        [
            # Query at D: both D and D+1 ITXs rolled back (>= D) -> $40 - $40 = $0
            (date(2026, 3, 1), Decimal("0")),
            # Query at D+1: only D+1 ITX rolled back -> $40 - $20 = $20
            (date(2026, 3, 2), Decimal("20")),
        ],
    )
    def test_consecutive_days_rollback_arithmetic(
        self,
        make_account: Callable[..., BankAccount],
        system_user: User,  # type: ignore[valid-type]
        query_date: date,
        expected_balance: Decimal,
    ) -> None:
        """
        GIVEN: two system-issued ITXs each crediting $20 to a budget --
               one dated March 1, one dated March 2 -- so current balance is $40
        WHEN:  state_at_start_of_D is called with a query date (parametrized)
        THEN:  every system ITX whose date is on or after the query date is rolled
               back, so querying March 1 yields $0 (both undone) while querying
               March 2 yields $20 (only the March 2 ITX undone)
        """
        D = date(2026, 3, 1)
        account = make_account(posted_through=D + timedelta(days=1))
        unallocated = account.unallocated_budget
        assert unallocated is not None
        Budget.objects.filter(pkid=unallocated.pkid).update(
            balance=Money(500, "USD")
        )
        budget = budget_svc.create(
            bank_account=account,
            name="Test Goal",
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(500, "USD"),
            funding_amount=Money(20, "USD"),
            funding_schedule=_MONTHLY,
        )

        for event_date in (D, D + timedelta(days=1)):
            eff = datetime(
                event_date.year, event_date.month, event_date.day, tzinfo=UTC
            )
            itx = internal_transaction_svc.create(
                bank_account=account,
                src_budget=unallocated,
                dst_budget=budget,
                amount=Money(20, "USD"),
                actor=system_user,
                effective_date=eff,
            )
            InternalTransaction.objects.filter(pk=itx.pk).update(
                system_event_date=event_date
            )

        budget.refresh_from_db()
        assert budget.balance == Money(40, "USD")

        balance_0, _ = state_at_start_of_D(budget, query_date)

        assert balance_0 == Money(expected_balance, "USD")
