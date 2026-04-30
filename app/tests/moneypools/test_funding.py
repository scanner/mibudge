#!/usr/bin/env python
#
"""
Tests for the budget funding engine (moneypools/service/funding.py),
the fund_budgets management command, the Celery fan-out tasks, and the
mark-imported REST endpoint.
"""

# system imports
#
from collections.abc import Callable
from datetime import date, datetime
from unittest.mock import patch

# 3rd party imports
#
import pytest
import recurrence
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from djmoney.money import Money

# Project imports
#
from moneypools.models import BankAccount, Budget, InternalTransaction
from moneypools.service import budget as budget_svc
from moneypools.service import funding as funding_svc
from moneypools.tasks import fund_all_accounts, fund_one_account
from tests.users.factories import UserFactory

User = get_user_model()

pytestmark = pytest.mark.django_db

# Fires on the 1st of each month -- dtstart on the Recurrence is what
# the library uses to anchor the day-of-month; the Rule alone is ignored.
_MONTHLY = recurrence.Recurrence(
    dtstart=datetime(2026, 1, 1),
    rrules=[recurrence.Rule(recurrence.MONTHLY)],
)


########################################################################
########################################################################
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
    """Return a factory that creates a BankAccount with optional last_posted_through."""

    def _make(posted_through: date | None = None) -> BankAccount:
        return bank_account_factory(last_posted_through=posted_through)

    return _make


########################################################################
########################################################################
#
class TestFundingEngineSingleEvent:
    """End-to-end: single funding event for FIXED_AMOUNT and TARGET_DATE."""

    ####################################################################
    #
    def test_fixed_amount_transfers_from_unallocated_to_budget(
        self,
        make_account: Callable[..., BankAccount],
        system_user: User,  # type: ignore[valid-type]
    ) -> None:
        """
        GIVEN: a GOAL budget with FIXED_AMOUNT $50/month, unallocated=$200,
               last_posted_through covers today
        WHEN:  fund_account is called
        THEN:  $50 is transferred; last_funded_on advances; 1 transfer reported
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
            name="New High-tech Overpriced Sneakers",
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(300, "USD"),
            funding_amount=Money(50, "USD"),
            funding_schedule=_MONTHLY,
        )
        Budget.objects.filter(pkid=budget.pkid).update(
            last_funded_on=date(2026, 2, 28)
        )

        report = funding_svc.fund_account(account, today, system_user)

        assert report.deferred is False
        assert report.transfers == 1
        assert not report.warnings

        budget.refresh_from_db()
        assert budget.last_funded_on == today
        assert budget.balance == Money(50, "USD")

        unallocated.refresh_from_db()
        assert unallocated.balance == Money(150, "USD")

    ####################################################################
    #
    def test_target_date_spreads_gap_over_remaining_occurrences(
        self,
        make_account: Callable[..., BankAccount],
        system_user: User,  # type: ignore[valid-type]
    ) -> None:
        """
        GIVEN: a GOAL budget with TARGET_DATE, gap=$300, 3 monthly events left
        WHEN:  fund_account fires on the first event
        THEN:  $100 is transferred ($300 / 3 remaining)
        """
        today = date(2026, 1, 1)
        account = make_account(posted_through=today)
        unallocated = account.unallocated_budget
        assert unallocated is not None
        Budget.objects.filter(pkid=unallocated.pkid).update(
            balance=Money(500, "USD")
        )

        budget = budget_svc.create(
            bank_account=account,
            name="Vacation",
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.TARGET_DATE,
            target_balance=Money(300, "USD"),
            target_date=date(2026, 3, 1),
            funding_schedule=_MONTHLY,
        )
        Budget.objects.filter(pkid=budget.pkid).update(
            last_funded_on=date(2025, 12, 31)
        )

        report = funding_svc.fund_account(account, today, system_user)

        assert report.transfers == 1
        budget.refresh_from_db()
        # 3 occurrences: Jan 1, Feb 1, Mar 1 → $300 / 3 = $100
        assert budget.balance == Money(100, "USD")


########################################################################
########################################################################
#
class TestFundingEngineRecurringWithFillup:
    """Recurring + with_fillup_goal: fund into fillup, recur into recurring."""

    ####################################################################
    #
    def test_fund_event_goes_into_fillup_goal(
        self,
        make_account: Callable[..., BankAccount],
        system_user: User,  # type: ignore[valid-type]
    ) -> None:
        """
        GIVEN: RECURRING/with_fillup_goal budget, funding schedule monthly
        WHEN:  fund event fires
        THEN:  money moves unallocated -> fillup_goal (not recurring budget)
        """
        today = date(2026, 2, 1)
        account = make_account(posted_through=today)
        unallocated = account.unallocated_budget
        assert unallocated is not None
        Budget.objects.filter(pkid=unallocated.pkid).update(
            balance=Money(200, "USD")
        )

        recurring = budget_svc.create(
            bank_account=account,
            name="Monthly Bills",
            budget_type=Budget.BudgetType.RECURRING,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(100, "USD"),
            funding_amount=Money(80, "USD"),
            funding_schedule=_MONTHLY,
            with_fillup_goal=True,
        )
        recurring.refresh_from_db()
        fillup = recurring.fillup_goal
        assert fillup is not None

        Budget.objects.filter(pkid=recurring.pkid).update(
            last_funded_on=date(2026, 1, 31)
        )

        report = funding_svc.fund_account(account, today, system_user)

        assert report.transfers == 1
        recurring.refresh_from_db()
        fillup.refresh_from_db()
        # Money lands in fillup, not the recurring budget itself
        assert fillup.balance == Money(80, "USD")
        assert recurring.balance == Money(0, "USD")

    ####################################################################
    #
    def test_recur_event_drains_fillup_into_recurring(
        self,
        make_account: Callable[..., BankAccount],
        system_user: User,  # type: ignore[valid-type]
    ) -> None:
        """
        GIVEN: fillup has $80, recurring target=$100, balance=$0, recur fires
        WHEN:  recur event processed
        THEN:  $80 moves fillup -> recurring; warning for underfunded;
               last_recurrence_on advances
        """
        today = date(2026, 2, 1)
        account = make_account(posted_through=today)

        recurring = budget_svc.create(
            bank_account=account,
            name="Monthly Bills",
            budget_type=Budget.BudgetType.RECURRING,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(100, "USD"),
            funding_amount=Money(80, "USD"),
            funding_schedule=_MONTHLY,
            recurrance_schedule=_MONTHLY,
            with_fillup_goal=True,
        )
        recurring.refresh_from_db()
        fillup = recurring.fillup_goal
        assert fillup is not None

        # Seed fillup with $80 (short of the $100 target)
        Budget.objects.filter(pkid=fillup.pkid).update(balance=Money(80, "USD"))
        Budget.objects.filter(pkid=recurring.pkid).update(
            last_funded_on=today,
            last_recurrence_on=date(2026, 1, 31),
        )

        report = funding_svc.fund_account(account, today, system_user)

        assert report.transfers == 1
        assert len(report.warnings) == 1
        assert "underfunded" in report.warnings[0]

        recurring.refresh_from_db()
        fillup.refresh_from_db()
        assert recurring.balance == Money(80, "USD")
        assert fillup.balance == Money(0, "USD")
        assert recurring.last_recurrence_on == today

    ####################################################################
    #
    def test_same_date_fund_before_recur_ordering(
        self,
        make_account: Callable[..., BankAccount],
        system_user: User,  # type: ignore[valid-type]
    ) -> None:
        """
        GIVEN: RECURRING/with_fillup_goal budget; fund and recur both on
               the same date
        WHEN:  fund_account processes both events
        THEN:  fund fires first (money hits fillup), then recur (fillup ->
               recurring); ordering produces correct final balances
        """
        today = date(2026, 2, 1)
        account = make_account(posted_through=today)
        unallocated = account.unallocated_budget
        assert unallocated is not None
        Budget.objects.filter(pkid=unallocated.pkid).update(
            balance=Money(200, "USD")
        )

        recurring = budget_svc.create(
            bank_account=account,
            name="Monthly Bills",
            budget_type=Budget.BudgetType.RECURRING,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(100, "USD"),
            funding_amount=Money(100, "USD"),
            funding_schedule=_MONTHLY,
            recurrance_schedule=_MONTHLY,
            with_fillup_goal=True,
        )
        recurring.refresh_from_db()
        fillup = recurring.fillup_goal
        assert fillup is not None

        Budget.objects.filter(pkid=recurring.pkid).update(
            last_funded_on=date(2026, 1, 31),
            last_recurrence_on=date(2026, 1, 31),
        )

        report = funding_svc.fund_account(account, today, system_user)

        assert report.transfers == 2
        assert not report.warnings

        recurring.refresh_from_db()
        fillup.refresh_from_db()
        assert recurring.balance == Money(100, "USD")
        assert fillup.balance == Money(0, "USD")


########################################################################
########################################################################
#
class TestFundingEngineMultiPeriodCatchup:
    """Multi-period backlog processed in date-grouped order."""

    ####################################################################
    #
    def test_three_missed_cycles_processed_in_order(
        self,
        make_account: Callable[..., BankAccount],
        system_user: User,  # type: ignore[valid-type]
    ) -> None:
        """
        GIVEN: GOAL budget missed 3 monthly funding events
        WHEN:  fund_account runs with today = 3 months later
        THEN:  3 transfers happen; last_funded_on = latest event date
        """
        # today=Mar 15: window captures Jan 1, Feb 1, Mar 1 (3 events only)
        today = date(2026, 3, 15)
        account = make_account(posted_through=today)
        unallocated = account.unallocated_budget
        assert unallocated is not None
        Budget.objects.filter(pkid=unallocated.pkid).update(
            balance=Money(600, "USD")
        )

        budget = budget_svc.create(
            bank_account=account,
            name="Emergency Fund",
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(1000, "USD"),
            funding_amount=Money(100, "USD"),
            funding_schedule=_MONTHLY,
        )
        # Last funded Dec 31 -- missed Jan 1, Feb 1, Mar 1 events
        Budget.objects.filter(pkid=budget.pkid).update(
            last_funded_on=date(2025, 12, 31)
        )

        report = funding_svc.fund_account(account, today, system_user)

        assert report.transfers == 3
        budget.refresh_from_db()
        assert budget.last_funded_on == date(2026, 3, 1)
        assert budget.balance == Money(300, "USD")


########################################################################
########################################################################
#
class TestImportFreshnessGate:
    """Gate: account deferred when last_posted_through < gate_date."""

    ####################################################################
    #
    def test_deferred_when_last_posted_through_is_behind(
        self,
        make_account: Callable[..., BankAccount],
        system_user: User,  # type: ignore[valid-type]
    ) -> None:
        """
        GIVEN: due event on 2026-03-01, last_posted_through=2026-02-28
        WHEN:  fund_account runs
        THEN:  report.deferred=True; no transfers; no DB changes
        """
        today = date(2026, 3, 1)
        account = make_account(posted_through=date(2026, 2, 28))
        unallocated = account.unallocated_budget
        assert unallocated is not None
        Budget.objects.filter(pkid=unallocated.pkid).update(
            balance=Money(200, "USD")
        )

        budget = budget_svc.create(
            bank_account=account,
            name="New High-tech Overpriced Sneakers",
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(300, "USD"),
            funding_amount=Money(50, "USD"),
            funding_schedule=_MONTHLY,
        )
        Budget.objects.filter(pkid=budget.pkid).update(
            last_funded_on=date(2026, 2, 28)
        )

        report = funding_svc.fund_account(account, today, system_user)

        assert report.deferred is True
        assert report.transfers == 0
        assert (
            InternalTransaction.objects.filter(bank_account=account).count()
            == 0
        )

    ####################################################################
    #
    def test_advance_posted_through_unblocks_backlog(
        self,
        make_account: Callable[..., BankAccount],
        system_user: User,  # type: ignore[valid-type]
    ) -> None:
        """
        GIVEN: account deferred; then last_posted_through advanced to cover gate
        WHEN:  fund_account runs again
        THEN:  backlog processed normally
        """
        today = date(2026, 3, 1)
        account = make_account(posted_through=date(2026, 2, 28))
        unallocated = account.unallocated_budget
        assert unallocated is not None
        Budget.objects.filter(pkid=unallocated.pkid).update(
            balance=Money(200, "USD")
        )

        budget = budget_svc.create(
            bank_account=account,
            name="New High-tech Overpriced Sneakers",
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(300, "USD"),
            funding_amount=Money(50, "USD"),
            funding_schedule=_MONTHLY,
        )
        Budget.objects.filter(pkid=budget.pkid).update(
            last_funded_on=date(2026, 2, 28)
        )

        # First run: deferred
        report = funding_svc.fund_account(account, today, system_user)
        assert report.deferred is True

        # Advance coverage past the gate then re-run
        BankAccount.objects.filter(pkid=account.pkid).update(
            last_posted_through=today
        )
        account.refresh_from_db()

        report = funding_svc.fund_account(account, today, system_user)
        assert report.deferred is False
        assert report.transfers == 1

    ####################################################################
    #
    def test_deferred_when_last_posted_through_is_none(
        self,
        make_account: Callable[..., BankAccount],
        system_user: User,  # type: ignore[valid-type]
    ) -> None:
        """
        GIVEN: brand-new account with no imports (last_posted_through=None)
        WHEN:  fund_account runs with a due event
        THEN:  report.deferred=True
        """
        today = date(2026, 3, 1)
        account = make_account(posted_through=None)
        unallocated = account.unallocated_budget
        assert unallocated is not None
        Budget.objects.filter(pkid=unallocated.pkid).update(
            balance=Money(200, "USD")
        )

        budget = budget_svc.create(
            bank_account=account,
            name="New High-tech Overpriced Sneakers",
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(300, "USD"),
            funding_amount=Money(50, "USD"),
            funding_schedule=_MONTHLY,
        )
        Budget.objects.filter(pkid=budget.pkid).update(
            last_funded_on=date(2026, 2, 28)
        )

        report = funding_svc.fund_account(account, today, system_user)
        assert report.deferred is True


########################################################################
########################################################################
#
class TestCapAndWarn:
    """Insufficient balance: cap transfer, log warning, advance pointers."""

    ####################################################################
    #
    def test_insufficient_unallocated_caps_and_warns(
        self,
        make_account: Callable[..., BankAccount],
        system_user: User,  # type: ignore[valid-type]
    ) -> None:
        """
        GIVEN: unallocated=$20, budget wants $50
        WHEN:  fund event fires
        THEN:  $20 transferred; warning logged; last_funded_on advances
        """
        today = date(2026, 3, 1)
        account = make_account(posted_through=today)
        unallocated = account.unallocated_budget
        assert unallocated is not None
        Budget.objects.filter(pkid=unallocated.pkid).update(
            balance=Money(20, "USD")
        )

        budget = budget_svc.create(
            bank_account=account,
            name="New High-tech Overpriced Sneakers",
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(300, "USD"),
            funding_amount=Money(50, "USD"),
            funding_schedule=_MONTHLY,
        )
        Budget.objects.filter(pkid=budget.pkid).update(
            last_funded_on=date(2026, 2, 28)
        )

        report = funding_svc.fund_account(account, today, system_user)

        assert report.transfers == 1
        assert len(report.warnings) == 1
        assert "capped" in report.warnings[0]

        budget.refresh_from_db()
        assert budget.balance == Money(20, "USD")
        assert budget.last_funded_on == today

    ####################################################################
    #
    def test_empty_unallocated_skips_but_advances_pointer(
        self,
        make_account: Callable[..., BankAccount],
        system_user: User,  # type: ignore[valid-type]
    ) -> None:
        """
        GIVEN: unallocated=$0
        WHEN:  fund event fires
        THEN:  no transfer; warning logged; last_funded_on still advances
        """
        today = date(2026, 3, 1)
        account = make_account(posted_through=today)
        unallocated = account.unallocated_budget
        assert unallocated is not None
        Budget.objects.filter(pkid=unallocated.pkid).update(
            balance=Money(0, "USD")
        )

        budget = budget_svc.create(
            bank_account=account,
            name="New High-tech Overpriced Sneakers",
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(300, "USD"),
            funding_amount=Money(50, "USD"),
            funding_schedule=_MONTHLY,
        )
        Budget.objects.filter(pkid=budget.pkid).update(
            last_funded_on=date(2026, 2, 28)
        )

        report = funding_svc.fund_account(account, today, system_user)

        assert report.transfers == 0
        assert len(report.warnings) == 1
        assert "empty" in report.warnings[0]

        budget.refresh_from_db()
        assert budget.last_funded_on == today

    ####################################################################
    #
    def test_insufficient_fillup_caps_and_warns_on_recur(
        self,
        make_account: Callable[..., BankAccount],
        system_user: User,  # type: ignore[valid-type]
    ) -> None:
        """
        GIVEN: fillup=$30, recurring target=$100, recur event fires
        WHEN:  recur event processed
        THEN:  $30 transferred; underfunded warning; last_recurrence_on advances
        """
        today = date(2026, 2, 1)
        account = make_account(posted_through=today)

        recurring = budget_svc.create(
            bank_account=account,
            name="Bills",
            budget_type=Budget.BudgetType.RECURRING,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(100, "USD"),
            funding_amount=Money(100, "USD"),
            funding_schedule=_MONTHLY,
            recurrance_schedule=_MONTHLY,
            with_fillup_goal=True,
        )
        recurring.refresh_from_db()
        fillup = recurring.fillup_goal
        assert fillup is not None

        Budget.objects.filter(pkid=fillup.pkid).update(balance=Money(30, "USD"))
        Budget.objects.filter(pkid=recurring.pkid).update(
            last_funded_on=today,
            last_recurrence_on=date(2026, 1, 31),
        )

        report = funding_svc.fund_account(account, today, system_user)

        assert report.transfers == 1
        assert len(report.warnings) == 1

        recurring.refresh_from_db()
        assert recurring.balance == Money(30, "USD")
        assert recurring.last_recurrence_on == today


########################################################################
########################################################################
#
class TestGoalCompletion:
    """Goal budgets: complete=True when target hit; sticky; not re-funded."""

    ####################################################################
    #
    def test_goal_marked_complete_when_target_reached(
        self,
        make_account: Callable[..., BankAccount],
        system_user: User,  # type: ignore[valid-type]
    ) -> None:
        """
        GIVEN: GOAL budget balance=$250, target=$300, funding=$50
        WHEN:  fund event fires
        THEN:  balance=$300; complete=True
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
            name="New High-tech Overpriced Sneakers",
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(300, "USD"),
            funding_amount=Money(50, "USD"),
            funding_schedule=_MONTHLY,
        )
        Budget.objects.filter(pkid=budget.pkid).update(
            balance=Money(250, "USD"),
            last_funded_on=date(2026, 2, 28),
        )

        funding_svc.fund_account(account, today, system_user)

        budget.refresh_from_db()
        assert budget.balance == Money(300, "USD")
        assert budget.complete is True

    ####################################################################
    #
    def test_complete_goal_skipped_on_subsequent_runs(
        self,
        make_account: Callable[..., BankAccount],
        system_user: User,  # type: ignore[valid-type]
    ) -> None:
        """
        GIVEN: GOAL budget complete=True
        WHEN:  fund_account runs
        THEN:  no transfers; budget balance unchanged
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
            name="New High-tech Overpriced Sneakers",
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(300, "USD"),
            funding_amount=Money(50, "USD"),
            funding_schedule=_MONTHLY,
        )
        Budget.objects.filter(pkid=budget.pkid).update(
            balance=Money(300, "USD"),
            complete=True,
            last_funded_on=date(2026, 2, 28),
        )

        report = funding_svc.fund_account(account, today, system_user)

        assert report.transfers == 0
        budget.refresh_from_db()
        assert budget.balance == Money(300, "USD")

    ####################################################################
    #
    def test_complete_stays_sticky_after_spending_below_target(
        self,
        make_account: Callable[..., BankAccount],
        system_user: User,  # type: ignore[valid-type]
    ) -> None:
        """
        GIVEN: GOAL budget complete=True, balance=$300 (target); user spends
               $100 so balance drops to $200 (below target)
        WHEN:  fund_account runs on the next month's event
        THEN:  no transfers; complete stays True; balance unchanged at $200
        """
        today = date(2026, 4, 1)
        account = make_account(posted_through=today)
        unallocated = account.unallocated_budget
        assert unallocated is not None
        Budget.objects.filter(pkid=unallocated.pkid).update(
            balance=Money(200, "USD")
        )

        budget = budget_svc.create(
            bank_account=account,
            name="New High-tech Overpriced Sneakers",
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(300, "USD"),
            funding_amount=Money(50, "USD"),
            funding_schedule=_MONTHLY,
        )
        # Simulate: goal completed in March, user spent $100 in April
        Budget.objects.filter(pkid=budget.pkid).update(
            balance=Money(200, "USD"),
            complete=True,
            last_funded_on=date(2026, 3, 1),
        )

        report = funding_svc.fund_account(account, today, system_user)

        assert report.transfers == 0
        budget.refresh_from_db()
        assert budget.complete is True
        assert budget.balance == Money(200, "USD")


########################################################################
########################################################################
#
class TestPausedAndArchived:
    """Paused / archived budgets are skipped."""

    ####################################################################
    #
    @pytest.mark.parametrize("paused", [True, False])
    def test_paused_budget_skipped(
        self,
        make_account: Callable[..., BankAccount],
        system_user: User,  # type: ignore[valid-type]
        paused: bool,
    ) -> None:
        """
        GIVEN: one paused budget, one active budget (parametrized)
        WHEN:  fund_account runs
        THEN:  paused budget gets no transfer; active budget is funded;
               paused name appears in report.skipped_budgets when paused=True
        """
        today = date(2026, 3, 1)
        account = make_account(posted_through=today)
        unallocated = account.unallocated_budget
        assert unallocated is not None
        Budget.objects.filter(pkid=unallocated.pkid).update(
            balance=Money(200, "USD")
        )

        active = budget_svc.create(
            bank_account=account,
            name="Active",
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(300, "USD"),
            funding_amount=Money(50, "USD"),
            funding_schedule=_MONTHLY,
        )
        paused_budget = budget_svc.create(
            bank_account=account,
            name="Paused",
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(300, "USD"),
            funding_amount=Money(50, "USD"),
            funding_schedule=_MONTHLY,
            paused=paused,
        )
        Budget.objects.filter(
            pkid__in=[active.pkid, paused_budget.pkid]
        ).update(last_funded_on=date(2026, 2, 28))

        report = funding_svc.fund_account(account, today, system_user)

        if paused:
            assert report.transfers == 1
            assert "Paused" in report.skipped_budgets
            paused_budget.refresh_from_db()
            assert paused_budget.balance == Money(0, "USD")
        else:
            assert report.transfers == 2
            assert not report.skipped_budgets

    ####################################################################
    #
    def test_archived_budget_skipped(
        self,
        make_account: Callable[..., BankAccount],
        system_user: User,  # type: ignore[valid-type]
    ) -> None:
        """
        GIVEN: an archived budget with a due funding event
        WHEN:  fund_account runs
        THEN:  no transfer for the archived budget
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
            name="Old Savings",
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(300, "USD"),
            funding_amount=Money(50, "USD"),
            funding_schedule=_MONTHLY,
            archived=True,
        )
        Budget.objects.filter(pkid=budget.pkid).update(
            last_funded_on=date(2026, 2, 28)
        )

        report = funding_svc.fund_account(account, today, system_user)

        assert report.transfers == 0
        budget.refresh_from_db()
        assert budget.balance == Money(0, "USD")


########################################################################
########################################################################
#
class TestIdempotency:
    """Re-running the engine on the same day produces no duplicate transfers."""

    ####################################################################
    #
    def test_same_day_rerun_is_idempotent(
        self,
        make_account: Callable[..., BankAccount],
        system_user: User,  # type: ignore[valid-type]
    ) -> None:
        """
        GIVEN: fund_account ran successfully today (last_funded_on=today)
        WHEN:  fund_account runs again with the same today date
        THEN:  no new transfers; exactly one InternalTransaction in total
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
            name="New High-tech Overpriced Sneakers",
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(300, "USD"),
            funding_amount=Money(50, "USD"),
            funding_schedule=_MONTHLY,
        )
        Budget.objects.filter(pkid=budget.pkid).update(
            last_funded_on=date(2026, 2, 28)
        )

        report1 = funding_svc.fund_account(account, today, system_user)
        assert report1.transfers == 1

        report2 = funding_svc.fund_account(account, today, system_user)
        assert report2.transfers == 0

        assert (
            InternalTransaction.objects.filter(
                bank_account=account,
                dst_budget=budget,
            ).count()
            == 1
        )


########################################################################
########################################################################
#
class TestCeleryFanOut:
    """fund_all_accounts fans out one fund_one_account per account."""

    ####################################################################
    #
    def test_fund_all_accounts_dispatches_one_task_per_account(
        self,
        bank_account_factory: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: 3 bank accounts exist
        WHEN:  fund_all_accounts runs
        THEN:  fund_one_account.apply_async called exactly 3 times with
               each account's UUID and a non-negative countdown
        """
        accounts = [bank_account_factory() for _ in range(3)]
        account_ids = {str(a.id) for a in accounts}

        with patch(
            "moneypools.tasks.fund_one_account.apply_async"
        ) as mock_dispatch:
            fund_all_accounts()

        assert mock_dispatch.call_count == 3
        dispatched_ids = {
            call.kwargs["args"][0] for call in mock_dispatch.call_args_list
        }
        assert dispatched_ids == account_ids

        for call in mock_dispatch.call_args_list:
            assert call.kwargs["countdown"] >= 0

    ####################################################################
    #
    def test_fund_one_account_calls_fund_account(
        self,
        bank_account_factory: Callable[..., BankAccount],
        system_user: User,  # type: ignore[valid-type]
    ) -> None:
        """
        GIVEN: a valid account and a funding-system user
        WHEN:  fund_one_account runs
        THEN:  funding_svc.fund_account is called with the correct account
        """
        account = bank_account_factory()

        with patch("moneypools.tasks.funding_svc.fund_account") as mock_fund:
            mock_fund.return_value = funding_svc.FundingReport(
                account_id=str(account.id)
            )
            fund_one_account(str(account.id))

        assert mock_fund.call_count == 1
        assert mock_fund.call_args.args[0].id == account.id


########################################################################
########################################################################
#
class TestMarkImportedEndpoint:
    """POST /api/v1/bank-accounts/<id>/mark-imported/"""

    ####################################################################
    #
    def _url(self, account: BankAccount) -> str:
        return reverse(
            "api_v1:bankaccount-mark-imported", kwargs={"id": str(account.id)}
        )

    ####################################################################
    #
    def test_sets_last_imported_at_and_last_posted_through(
        self,
        bank_account_factory: Callable[..., BankAccount],
        api_client,
    ) -> None:
        """
        GIVEN: authenticated owner, valid date in body
        WHEN:  POST mark-imported
        THEN:  200; last_imported_at set; last_posted_through=supplied date
        """
        account = bank_account_factory()
        owner = account.owners.first()
        api_client.force_authenticate(user=owner)

        resp = api_client.post(
            self._url(account),
            {"last_posted_through": "2026-03-15"},
            format="json",
        )
        assert resp.status_code == 200
        account.refresh_from_db()
        assert account.last_posted_through == date(2026, 3, 15)
        assert account.last_imported_at is not None

    ####################################################################
    #
    def test_monotonic_update_never_regresses(
        self,
        bank_account_factory: Callable[..., BankAccount],
        api_client,
    ) -> None:
        """
        GIVEN: last_posted_through=2026-03-15; POST with older date 2026-03-01
        WHEN:  POST mark-imported
        THEN:  last_posted_through stays 2026-03-15 (not regressed)
        """
        account = bank_account_factory()
        BankAccount.objects.filter(pkid=account.pkid).update(
            last_posted_through=date(2026, 3, 15)
        )
        owner = account.owners.first()
        api_client.force_authenticate(user=owner)

        resp = api_client.post(
            self._url(account),
            {"last_posted_through": "2026-03-01"},
            format="json",
        )
        assert resp.status_code == 200
        account.refresh_from_db()
        assert account.last_posted_through == date(2026, 3, 15)

    ####################################################################
    #
    def test_requires_authentication(
        self,
        bank_account_factory: Callable[..., BankAccount],
        api_client,
    ) -> None:
        """
        GIVEN: unauthenticated request
        WHEN:  POST mark-imported
        THEN:  401
        """
        account = bank_account_factory()
        resp = api_client.post(
            self._url(account),
            {"last_posted_through": "2026-03-15"},
            format="json",
        )
        assert resp.status_code == 401

    ####################################################################
    #
    def test_rejects_non_owner(
        self,
        bank_account_factory: Callable[..., BankAccount],
        api_client,
    ) -> None:
        """
        GIVEN: authenticated user who does not own the account
        WHEN:  POST mark-imported
        THEN:  404 (ownership filter hides the account)
        """
        account = bank_account_factory()
        other_user = UserFactory()
        api_client.force_authenticate(user=other_user)

        resp = api_client.post(
            self._url(account),
            {"last_posted_through": "2026-03-15"},
            format="json",
        )
        assert resp.status_code == 404

    ####################################################################
    #
    @pytest.mark.parametrize(
        "body,expected_field",
        [
            ({}, "last_posted_through"),
            ({"last_posted_through": "not-a-date"}, "last_posted_through"),
            ({"last_posted_through": ""}, "last_posted_through"),
        ],
    )
    def test_validation_errors(
        self,
        bank_account_factory: Callable[..., BankAccount],
        api_client,
        body: dict,
        expected_field: str,
    ) -> None:
        """
        GIVEN: missing or malformed last_posted_through
        WHEN:  POST mark-imported
        THEN:  400 with error on the relevant field
        """
        account = bank_account_factory()
        owner = account.owners.first()
        api_client.force_authenticate(user=owner)

        resp = api_client.post(self._url(account), body, format="json")
        assert resp.status_code == 400
        assert expected_field in resp.data
