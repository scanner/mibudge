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
import pytest_check as check
import recurrence
from djmoney.money import Money

# Project imports
#
from moneypools.models import BankAccount, Budget, InternalTransaction
from moneypools.service import internal_transaction as internal_transaction_svc
from moneypools.service.funding_strategy import (
    BUDGET_TYPE_TO_STRATEGY,
    CappedStrategy,
    EventKind,
    GoalStrategy,
    RecurringStrategy,
    state_at_start_of_D,
)
from users.models import User

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

# Fires on the 15th and last day of each month, anchored at May 15.
# (Bare no-DTSTART schedules can no longer reach the database: the
# budget_pre_save signal anchors them; the fallback-anchor code paths
# are covered by the pure tests in test_schedules.py.)
_SEMI_MONTHLY_15_EOM = recurrence.Recurrence(
    dtstart=datetime(2026, 5, 15),
    rrules=[recurrence.Rule(recurrence.MONTHLY, bymonthday=[15, -1])],
)


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
        make_budget: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: a Goal budget configured to transfer $50 per fund event
        WHEN:  the strategy computes the intended amount for a fund event
        THEN:  returns $50 regardless of the current balance
        """
        budget = make_budget(
            make_account(),
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(300, "USD"),
            funding_amount=Money(50, "USD"),
            funding_schedule=_MONTHLY,
            stored={"balance": Money(100, "USD")},
        )

        result = GoalStrategy().intended_for_event(
            budget, date(2026, 3, 1), kind=EventKind.FUND
        )

        assert result == Money(50, "USD")

    ####################################################################
    #
    def test_fixed_amount_none_returns_zero(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: a Goal budget with no funding amount configured
        WHEN:  the strategy computes the intended amount
        THEN:  returns $0
        """
        budget = make_budget(
            make_account(),
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(100, "USD"),
            funding_schedule=_MONTHLY,
            stored={"funding_amount": None},
        )

        result = GoalStrategy().intended_for_event(
            budget, date(2026, 3, 1), kind=EventKind.FUND
        )

        assert result == Money(0, "USD")

    ####################################################################
    #
    def test_target_date_spreads_gap_over_remaining_events(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: a Goal budget with $300 still needed and three monthly fund events
               remaining before the target date (January, February, March)
        WHEN:  the strategy computes the intended amount for the January event
        THEN:  returns $100, spreading the gap evenly across the three events
        """
        budget = make_budget(
            make_account(),
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.TARGET_DATE,
            target_balance=Money(300, "USD"),
            target_date=date(2026, 3, 1),
            funding_schedule=_MONTHLY,
        )

        result = GoalStrategy().intended_for_event(
            budget, date(2026, 1, 1), kind=EventKind.FUND
        )

        # 3 occurrences Jan 1, Feb 1, Mar 1 -> $300 / 3 = $100
        assert result == Money(100, "USD")

    ####################################################################
    #
    def test_target_date_past_deadline_returns_full_gap(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: a Goal budget whose target date has already passed with $40 funded out of $100
        WHEN:  the strategy computes the intended amount for a fund event after the deadline
        THEN:  returns the full $60 remaining gap (target minus funded_amount) in one event
        """
        budget = make_budget(
            make_account(),
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.TARGET_DATE,
            target_balance=Money(100, "USD"),
            target_date=date(2026, 1, 1),
            funding_schedule=_MONTHLY,
            stored={
                "balance": Money(40, "USD"),
                "funded_amount": Money(40, "USD"),
            },
        )

        # Event date after target_date: count_occurrences returns 1 (the floor)
        # so the full remaining gap is returned.
        result = GoalStrategy().intended_for_event(
            budget, date(2026, 3, 1), kind=EventKind.FUND
        )

        assert result == Money(60, "USD")

    ####################################################################
    #
    @pytest.mark.parametrize(
        "event_date,funded,expected",
        [
            # Two events remain (Jul 15, Jul 31): $1,098 / 2 = $549.
            (date(2026, 7, 15), Decimal("5602.00"), Decimal("549.00")),
            # One event remains (Jul 31): the full remaining gap.
            (date(2026, 7, 31), Decimal("6151.00"), Decimal("549.00")),
        ],
    )
    def test_target_date_prespent_goal_spreads_remaining_gap(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
        event_date: date,
        funded: Decimal,
        expected: Decimal,
    ) -> None:
        """
        GIVEN: a pre-spent TARGET_DATE Goal (spending drove balance below
               funded_amount) on a semi-monthly schedule, matching a goal
               budget we saw: target $6,700 by Aug 1, $5,602 funded,
               $2,053.02 spent
        WHEN:  the strategy computes the intended amount for a fund event
        THEN:  the remaining gap (target - funded_amount) is spread over
               exactly the occurrences left before the target date --
               spending never widens the gap, and no extra event is
               counted
        """
        budget = make_budget(
            make_account(),
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.TARGET_DATE,
            target_balance=Money(Decimal("6700.00"), "USD"),
            target_date=date(2026, 8, 1),
            funding_schedule=_SEMI_MONTHLY_15_EOM,
            stored={
                "balance": Money(funded - Decimal("2053.02"), "USD"),
                "funded_amount": Money(funded, "USD"),
            },
        )

        result = GoalStrategy().intended_for_event(
            budget, event_date, kind=EventKind.FUND
        )

        assert result == Money(expected, "USD")

    ####################################################################
    #
    @pytest.mark.parametrize("complete", [True, False])
    def test_is_complete_mirrors_complete_flag(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
        complete: bool,
    ) -> None:
        """
        GIVEN: a Goal budget whose complete flag is True or False (parametrized)
        WHEN:  is_complete is called
        THEN:  returns exactly the value of the complete flag
        """
        budget = make_budget(
            make_account(),
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(100, "USD"),
            funding_amount=Money(25, "USD"),
            funding_schedule=_MONTHLY,
            stored={"complete": complete},
        )

        assert GoalStrategy().is_complete(budget) is complete


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
        make_budget: Callable[..., Budget],
        system_user: User,
    ) -> None:
        """
        GIVEN: a Goal budget with target $100 and an Unallocated source budget
        WHEN:  a credit brings funded_amount to exactly $100
        THEN:  complete flips to True; a second credit keeps complete=True
               and funded_amount continues to grow; deleting the first credit
               reverses funded_amount but leaves complete=True (high-water mark)
        """
        account = make_account(unallocated=300)
        unallocated = account.unallocated_budget
        assert unallocated is not None
        goal = make_budget(
            account,
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(100, "USD"),
            funding_amount=Money(60, "USD"),
            funding_schedule=_MONTHLY,
        )

        def credit(amount: int) -> InternalTransaction:
            itx = internal_transaction_svc.create(
                bank_account=account,
                src_budget=unallocated,
                dst_budget=goal,
                amount=Money(amount, "USD"),
                actor=system_user,
            )
            goal.refresh_from_db()
            return itx

        # $60 -- below threshold, the latch does not fire.
        credit(60)
        assert (goal.funded_amount, goal.complete) == (Money(60, "USD"), False)

        # $40 -- funded_amount reaches exactly $100 (the threshold).
        threshold_itx = credit(40)
        assert (goal.funded_amount, goal.complete) == (Money(100, "USD"), True)

        # $10 -- funded_amount rises above target; complete stays True.
        credit(10)
        assert (goal.funded_amount, goal.complete) == (Money(110, "USD"), True)

        # Deleting the threshold-crossing credit lowers funded_amount but
        # does not clear complete -- it is a high-water mark.
        internal_transaction_svc.delete(threshold_itx)
        goal.refresh_from_db()

        check.equal(goal.funded_amount, Money(70, "USD"), "credit reversed")
        check.is_true(goal.complete, "latch stays set")


########################################################################
########################################################################
#
class TestCappedStrategy:
    """Unit tests for CappedStrategy.intended_for_event and is_complete."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "balance,expected",
        [
            # funding_amount < gap -> funding_amount
            pytest.param(10, 20, id="below_gap"),
            # funding_amount > gap -> the gap
            pytest.param(40, 10, id="capped_by_gap"),
            # already at the $50 target -> nothing
            pytest.param(50, 0, id="at_target"),
        ],
    )
    def test_returns_min_of_funding_amount_and_gap(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
        balance: int,
        expected: int,
    ) -> None:
        """
        GIVEN: a Capped budget funded $20 toward a $50 target, at a
               given balance (parametrized)
        WHEN:  the strategy computes the intended amount
        THEN:  returns whichever is smaller -- the configured funding
               amount or the remaining gap to target (zero at target)
        """
        budget = make_budget(
            make_account(),
            budget_type=Budget.BudgetType.CAPPED,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(50, "USD"),
            funding_amount=Money(20, "USD"),
            funding_schedule=_MONTHLY,
            stored={"balance": Money(balance, "USD")},
        )

        result = CappedStrategy().intended_for_event(
            budget, date(2026, 3, 1), kind=EventKind.FUND
        )

        assert result == Money(expected, "USD")

    ####################################################################
    #
    def test_is_complete_always_false(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: a Capped budget at full balance
        WHEN:  is_complete is called
        THEN:  returns False because Capped budgets are never marked complete
        """
        budget = make_budget(
            make_account(),
            budget_type=Budget.BudgetType.CAPPED,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(100, "USD"),
            funding_amount=Money(20, "USD"),
            funding_schedule=_MONTHLY,
            stored={"balance": Money(100, "USD")},
        )

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
        make_budget: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: a Recurring budget whose fill-up has $80 still needed,
               with two fund events (Feb 10 and Feb 20) remaining before the March 1 recur date
        WHEN:  the strategy computes the intended fund-event amount for Feb 10
        THEN:  returns $40, splitting the fill-up gap evenly across the two remaining events
        """
        # The fill-up starts at 0, so the full $80 is the gap.
        recurring = make_budget(
            make_account(),
            budget_type=Budget.BudgetType.RECURRING,
            funding_type=Budget.FundingType.TARGET_DATE,
            target_balance=Money(80, "USD"),
            funding_schedule=_TWICE_MONTHLY,
            recurrence_schedule=_MONTHLY_FIRST,
            stored={
                "last_funded_on": date(2026, 2, 9),
                "last_recurrence_on": date(2026, 2, 1),
            },
        )

        result = RecurringStrategy().intended_for_event(
            recurring, date(2026, 2, 10), kind=EventKind.FUND
        )

        # 2 fund events in the cycle (Feb 10, Feb 20): $80 / 2 = $40
        assert result == Money(40, "USD")

    ####################################################################
    #
    @pytest.mark.parametrize(
        "balance,expected",
        [
            # The engine caps this against the fill-up balance.
            pytest.param(30, 70, id="gap"),
            pytest.param(100, 0, id="at_target"),
        ],
    )
    def test_recur_event_returns_gap(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
        balance: int,
        expected: int,
    ) -> None:
        """
        GIVEN: a $100 Recurring budget at a given balance (parametrized)
        WHEN:  the strategy computes the intended recur-event amount
        THEN:  returns the full gap to target -- zero when already there
        """
        recurring = make_budget(
            make_account(),
            budget_type=Budget.BudgetType.RECURRING,
            funding_type=Budget.FundingType.TARGET_DATE,
            target_balance=Money(100, "USD"),
            funding_schedule=_MONTHLY,
            recurrence_schedule=_MONTHLY,
            stored={"balance": Money(balance, "USD")},
        )

        result = RecurringStrategy().intended_for_event(
            recurring, date(2026, 3, 1), kind=EventKind.RECUR
        )

        assert result == Money(expected, "USD")

    ####################################################################
    #
    def test_is_complete_always_false(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: a Recurring budget
        WHEN:  is_complete is called
        THEN:  returns False because the Recurring strategy never reports completion
        """
        recurring = make_budget(
            make_account(),
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

    D = date(2026, 3, 1)

    ####################################################################
    #
    @pytest.fixture
    def credited_budget(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
    ) -> Budget:
        """A Goal holding $100, on an account with $500 in Unallocated."""
        return make_budget(
            make_account(
                posted_through=self.D + timedelta(days=1), unallocated=500
            ),
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(500, "USD"),
            funding_amount=Money(20, "USD"),
            funding_schedule=_MONTHLY,
            stored={"balance": Money(100, "USD")},
        )

    ####################################################################
    #
    @pytest.fixture
    def make_system_credit(
        self, system_user: User
    ) -> Callable[[Budget, date], InternalTransaction]:
        """Return a factory for $20 system credits from Unallocated.

        Returns:
            A callable `(budget, on) -> InternalTransaction` crediting
            `budget` $20 with an effective date of midnight UTC on `on`,
            stamped as a system event on that date.
        """

        def _make(budget: Budget, on: date) -> InternalTransaction:
            unallocated = budget.bank_account.unallocated_budget
            assert unallocated is not None
            itx = internal_transaction_svc.create(
                bank_account=budget.bank_account,
                src_budget=unallocated,
                dst_budget=budget,
                amount=Money(20, "USD"),
                actor=system_user,
                effective_date=datetime(on.year, on.month, on.day, tzinfo=UTC),
            )
            InternalTransaction.objects.filter(pk=itx.pk).update(
                system_event_date=on
            )
            return itx

        return _make

    ####################################################################
    #
    @pytest.mark.parametrize(
        "credit_offsets,query_offset,expected",
        [
            # Nothing on or after D: the current $100 is returned.
            pytest.param([], 0, 100, id="no_system_credits"),
            # Querying D rolls back every credit dated on or after D
            # (D and D+1): $140 - $40.
            pytest.param([0, 1], 0, 100, id="rolls_back_on_and_after_D"),
            # Querying D+1 rolls back only the D+1 credit; the D credit
            # is before the query date and stays: $140 - $20.
            pytest.param([0, 1], 1, 120, id="keeps_credits_before_D"),
        ],
    )
    def test_rolls_back_system_credits_on_or_after_query_date(
        self,
        credited_budget: Budget,
        make_system_credit: Callable[[Budget, date], InternalTransaction],
        credit_offsets: list[int],
        query_offset: int,
        expected: int,
    ) -> None:
        """
        GIVEN: a Goal holding $100 plus $20 system credits dated D and/or
               D+1 (parametrized)
        WHEN:  state_at_start_of_D is called for D or D+1
        THEN:  every system credit dated on or after the query date is
               rolled back; earlier credits and the base balance remain
        """
        for offset in credit_offsets:
            make_system_credit(credited_budget, self.D + timedelta(days=offset))
        credited_budget.refresh_from_db()

        balance_0, _ = state_at_start_of_D(
            credited_budget, self.D + timedelta(days=query_offset)
        )

        assert balance_0 == Money(expected, "USD")
