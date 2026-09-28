"""Tests for the verify_balances management command."""

# system imports
from collections.abc import Callable
from decimal import Decimal
from io import StringIO

# 3rd party imports
import pytest
import pytest_check as check
from django.core.management import call_command
from django.core.management.base import CommandError
from djmoney.money import Money

# Project imports
from moneypools.models import BankAccount, Budget

pytestmark = pytest.mark.django_db


####################################################################
#
def _verify(*args: object) -> str:
    """Run verify_balances and return its stdout."""
    out = StringIO()
    call_command("verify_balances", *args, stdout=out)
    return out.getvalue()


########################################################################
########################################################################
#
class TestVerifyBalances:
    """Tests for verify_balances."""

    ####################################################################
    #
    def test_balanced_account_passes(self, account: BankAccount) -> None:
        """
        GIVEN: a freshly created bank account with zero available_balance
               and an auto-created zero-balance Unallocated budget
        WHEN:  verify_balances runs
        THEN:  the command succeeds with a PASS line for the account
        """
        output = _verify()
        check.is_in("PASS", output, "reports PASS")
        check.is_not_in("FAIL", output, "and no FAIL")

    ####################################################################
    #
    @pytest.mark.parametrize(
        "balance_field,expected_in_output",
        [
            # Only the available-balance check prints the per-budget
            # breakdown (available == sum of budget balances).
            ("available_balance", ["delta=100.00", "Unallocated"]),
            ("posted_balance", ["delta=100.00"]),
        ],
        ids=["available-mismatch", "posted-mismatch"],
    )
    def test_mismatch_raises_command_error(
        self,
        account: BankAccount,
        balance_field: str,
        expected_in_output: list[str],
    ) -> None:
        """
        GIVEN: an account whose available_balance or posted_balance does not
               match the expected value derived from budget balances
        WHEN:  verify_balances runs
        THEN:  the command raises CommandError and reports FAIL with a
               delta (and, for available_balance, the budget breakdown)
        """
        # Force an invariant break by pushing one balance field away from
        # its expected value (budget sum is zero for a fresh account).
        setattr(account, balance_field, Money("100.00", "USD"))
        account.save()

        out = StringIO()
        with pytest.raises(CommandError):
            call_command("verify_balances", stdout=out)
        output = out.getvalue()
        check.is_in("FAIL", output, "reports FAIL")
        for expected in expected_in_output:
            check.is_in(expected, output, "with the detail")

    ####################################################################
    #
    def test_tolerance_absorbs_small_delta(self, account: BankAccount) -> None:
        """
        GIVEN: an account that is off by a penny
        WHEN:  verify_balances runs with --tolerance 0.01
        THEN:  the account is reported as PASS
        """
        account.available_balance = Money("0.01", account.currency)
        account.save()

        assert "PASS" in _verify("--tolerance", Decimal("0.01"))


########################################################################
########################################################################
#
class TestVerifyBalancesGoalInvariant:
    """Tests for the Level 4 Goal funded_amount invariant check."""

    ####################################################################
    #
    @pytest.fixture
    def make_goal_holding_200(
        self, account: BankAccount, make_budget: Callable[..., Budget]
    ) -> Callable[..., Budget]:
        """Return a factory for a Goal holding $200 on a balanced account.

        The account's available and posted balances are set to the
        budget sum ($200; no pending transactions) so the Level 1 check
        stays clean and only the goal invariant is under test.

        Returns:
            A callable `(name, funded_amount) -> Budget`.
        """

        def _make(name: str, funded_amount: int) -> Budget:
            budget = make_budget(
                account,
                name=name,
                budget_type=Budget.BudgetType.GOAL,
                funding_type=Budget.FundingType.FIXED_AMOUNT,
                target_balance=Money("500.00", "USD"),
                funding_amount=Money("100.00", "USD"),
                stored={
                    "balance": Money("200.00", "USD"),
                    "funded_amount": Money(funded_amount, "USD"),
                },
            )
            account.available_balance = Money("200.00", "USD")
            account.posted_balance = Money("200.00", "USD")
            account.save()
            return budget

        return _make

    ####################################################################
    #
    def test_goal_with_consistent_funded_amount_passes(
        self, make_goal_holding_200: Callable[..., Budget]
    ) -> None:
        """
        GIVEN: a Goal budget where balance == funded_amount - spent_amount
               (no allocations, so spent=0 and balance == funded_amount)
        WHEN:  verify_balances runs
        THEN:  no goal-invariant failure is reported
        """
        make_goal_holding_200("Holiday Fund", funded_amount=200)

        output = _verify()
        check.is_not_in("FAIL", output, "no FAIL")
        check.is_in("0 goal-invariant failure(s)", output, "zero failures")

    ####################################################################
    #
    def test_goal_with_broken_funded_amount_fails(
        self, make_goal_holding_200: Callable[..., Budget]
    ) -> None:
        """
        GIVEN: a Goal budget where funded_amount does not match balance
               (simulating a bug that updated balance without funded_amount)
        WHEN:  verify_balances runs
        THEN:  a goal-invariant failure is reported and CommandError is raised
        """
        make_goal_holding_200("Broken Goal", funded_amount=50)

        out = StringIO()
        with pytest.raises(CommandError) as exc_info:
            call_command("verify_balances", stdout=out)
        output = out.getvalue()
        check.is_in("FAIL", output, "reports FAIL")
        check.is_in("Broken Goal", output, "names the goal")
        check.is_in("goal-invariant", str(exc_info.value), "error says why")
