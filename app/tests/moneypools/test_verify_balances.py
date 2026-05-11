"""Tests for the verify_balances management command."""

# system imports
from collections.abc import Callable
from decimal import Decimal
from io import StringIO

# 3rd party imports
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from djmoney.money import Money

# Project imports
from moneypools.models import BankAccount, Budget
from moneypools.service import budget as budget_svc

pytestmark = pytest.mark.django_db


########################################################################
####################################################################
#
class TestVerifyBalances:
    """Tests for verify_balances."""

    ####################################################################
    #
    def test_balanced_account_passes(
        self,
        bank_account_factory: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: a freshly created bank account with zero posted_balance
               and an auto-created zero-balance Unallocated budget
        WHEN:  verify_balances runs
        THEN:  the command succeeds with a PASS line for the account
        """
        bank_account_factory()
        out = StringIO()
        call_command("verify_balances", stdout=out)
        assert "PASS" in out.getvalue()
        assert "FAIL" not in out.getvalue()

    ####################################################################
    #
    def test_mismatch_raises_command_error(
        self,
        bank_account_factory: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: an account whose posted_balance does not equal the sum of
               its budget balances
        WHEN:  verify_balances runs
        THEN:  the command raises CommandError and reports the failing
               account with a per-budget breakdown
        """
        account = bank_account_factory()
        # Force an invariant break by pushing posted_balance away from
        # the sum of budget balances (which is zero for a fresh account).
        account.posted_balance = Money("100.00", account.currency)
        account.save()

        out = StringIO()
        with pytest.raises(CommandError):
            call_command("verify_balances", stdout=out)
        output = out.getvalue()
        assert "FAIL" in output
        assert "delta=100.00" in output
        # Per-budget breakdown should name the Unallocated budget.
        assert "Unallocated" in output

    ####################################################################
    #
    def test_tolerance_absorbs_small_delta(
        self,
        bank_account_factory: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: an account that is off by a penny
        WHEN:  verify_balances runs with --tolerance 0.01
        THEN:  the account is reported as PASS
        """
        account = bank_account_factory()
        account.posted_balance = Money("0.01", account.currency)
        account.save()

        out = StringIO()
        call_command(
            "verify_balances", "--tolerance", Decimal("0.01"), stdout=out
        )
        assert "PASS" in out.getvalue()


########################################################################
########################################################################
#
class TestVerifyBalancesGoalInvariant:
    """Tests for the Level 4 Goal funded_amount invariant check."""

    ####################################################################
    #
    def test_goal_with_consistent_funded_amount_passes(
        self,
        bank_account_factory: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: a Goal budget where balance == funded_amount - spent_amount
               (no allocations, so spent=0 and balance == funded_amount)
        WHEN:  verify_balances runs
        THEN:  no goal-invariant failure is reported
        """
        account = bank_account_factory()
        budget = budget_svc.create(
            bank_account=account,
            name="Holiday Fund",
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money("500.00", "USD"),
            funding_amount=Money("100.00", "USD"),
        )
        # Set balance and funded_amount to the same value so the invariant holds.
        Budget.objects.filter(pk=budget.pk).update(
            balance=Money("200.00", "USD"),
            funded_amount=Money("200.00", "USD"),
        )
        # Keep Level 1 clean: posted_balance must equal sum of budget balances.
        account.posted_balance = Money("200.00", "USD")
        account.save()

        out = StringIO()
        call_command("verify_balances", stdout=out)
        output = out.getvalue()
        assert "FAIL" not in output
        assert "0 goal-invariant failure(s)" in output

    ####################################################################
    #
    def test_goal_with_broken_funded_amount_fails(
        self,
        bank_account_factory: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: a Goal budget where funded_amount does not match balance
               (simulating a bug that updated balance without funded_amount)
        WHEN:  verify_balances runs
        THEN:  a goal-invariant failure is reported and CommandError is raised
        """
        account = bank_account_factory()
        budget = budget_svc.create(
            bank_account=account,
            name="Broken Goal",
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money("500.00", "USD"),
            funding_amount=Money("100.00", "USD"),
        )
        # Deliberately break the invariant: balance=200 but funded_amount=50.
        Budget.objects.filter(pk=budget.pk).update(
            balance=Money("200.00", "USD"),
            funded_amount=Money("50.00", "USD"),
        )
        # Also adjust the account posted_balance so Level 1 stays clean.
        account.posted_balance = Money("200.00", "USD")
        account.save()

        out = StringIO()
        with pytest.raises(CommandError) as exc_info:
            call_command("verify_balances", stdout=out)
        output = out.getvalue()
        assert "FAIL" in output
        assert "Broken Goal" in output
        assert "goal-invariant" in str(exc_info.value)
