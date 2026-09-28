"""Tests for the recompute_running_balances management command."""

# system imports
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from io import StringIO

# 3rd party imports
import pytest
import pytest_check as check
from django.core.management import call_command
from django.core.management.base import CommandError
from djmoney.money import Money

# Project imports
from moneypools.models import (
    BankAccount,
    Budget,
    Transaction,
    TransactionAllocation,
)
from moneypools.service import (
    transaction_allocation as transaction_allocation_svc,
)

pytestmark = pytest.mark.django_db


########################################################################
########################################################################
#
@dataclass
class BrokenChain:
    """An account whose balances and Unallocated chain were corrupted."""

    account: BankAccount
    unallocated: Budget
    # The payroll before the deleted one; its snapshot is left stale.
    payroll1: Transaction


########################################################################
########################################################################
#
class TestRecomputeAfterOrmDelete:
    """
    Tests that recompute_running_balances repairs budget_balance snapshot
    chains broken by an ORM-level transaction delete (e.g. via the Django
    admin), which bypasses the service layer and leaves both
    budget.balance and stored snapshots stale.
    """

    ####################################################################
    #
    @pytest.fixture
    def broken_chain(
        self,
        account: BankAccount,
        unallocated: Budget,
        make_budget: Callable[..., Budget],
        transaction_factory: Callable[..., Transaction],
    ) -> BrokenChain:
        """
        Three payroll credits in Unallocated and one expense in
        Groceries, then the middle payroll deleted through the ORM and
        the account balances corrupted.

        Before the damage the account is clean: Unallocated $9,000,
        Groceries -$200, posted_balance $8,800 = sum(budget balances).

        The ORM delete (as the Django admin does it) cascades to the
        payroll's Unallocated allocation but skips the service layer,
        so Unallocated.balance stays $9,000 and the remaining snapshots
        (payroll1 $3,000, payroll3 $9,000) no longer form a chain:
        walking forward from $9,000 - $6,000 of remaining allocations
        puts payroll1 at $6,000, not $3,000.  The account balances are
        then overwritten with $99,999 so the account-level repair is
        exercised too, not just the snapshot chain.
        """
        groceries = make_budget(
            account,
            name="Groceries",
            budget_type=Budget.BudgetType.CAPPED,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money("500.00", "USD"),
            funding_amount=Money("100.00", "USD"),
        )

        # Each payroll gets the default Unallocated allocation, with
        # snapshots $3,000, $6,000 and $9,000.
        payroll1, payroll2, _ = (
            transaction_factory(
                bank_account=account,
                amount=Money("3000.00", "USD"),
                posted_date=datetime(2026, month, 15, tzinfo=UTC),
                raw_description="PAYROLL DIRECT DEPOSIT",
            )
            for month in (1, 2, 3)
        )

        # The expense's default Unallocated allocation is moved to
        # Groceries, so Unallocated holds only the payrolls.
        expense = transaction_factory(
            bank_account=account,
            amount=Money("-200.00", "USD"),
            posted_date=datetime(2026, 3, 20, tzinfo=UTC),
            raw_description="GROCERY STORE PURCHASE",
        )
        transaction_allocation_svc.delete(
            TransactionAllocation.objects.get(
                transaction=expense, budget=unallocated
            )
        )
        transaction_allocation_svc.create(
            transaction=expense,
            budget=groceries,
            amount=Money("-200.00", "USD"),
        )

        out = StringIO()
        call_command("verify_balances", stdout=out)
        assert "FAIL" not in out.getvalue(), "Expected a clean baseline"

        Transaction.objects.filter(pk=payroll2.pk).delete()
        BankAccount.objects.filter(pk=account.pk).update(
            posted_balance=Money("99999.00", "USD"),
            available_balance=Money("99999.00", "USD"),
        )
        return BrokenChain(account, unallocated, payroll1)

    ####################################################################
    #
    def test_recompute_fixes_chain_broken_by_orm_delete(
        self, broken_chain: BrokenChain
    ) -> None:
        """
        GIVEN: an account with three payroll credits allocated to
               Unallocated and one expense reallocated to Groceries,
               where the middle payroll is subsequently deleted via
               the ORM
        WHEN:  recompute_running_balances runs
        THEN:  the broken budget_balance chain is repaired and a
               subsequent verify_balances run reports no failures
        """
        # verify_balances reports both failures first.  Level 1: the
        # posted balance ($99,999) differs from the budget sum ($8,800).
        # Level 3: payroll1's $3,000 snapshot is not the $6,000 running
        # value once payroll2 is gone.
        out = StringIO()
        with pytest.raises(CommandError):
            call_command("verify_balances", stdout=out)
        output = out.getvalue()
        assert "1 available-balance failure(s)" in output
        assert "1 budget-chain failure(s)" in output
        assert broken_chain.unallocated.name in output

        # Rewalks each budget's allocation chain against the current
        # budget.balance, and recomputes the account balances as
        # sum(budget.balance) - sum(pending amounts).
        call_command("recompute_running_balances", stderr=StringIO())

        out = StringIO()
        call_command("verify_balances", stdout=out)
        output = out.getvalue()
        check.is_not_in("FAIL", output, "verify_balances is clean")
        check.is_in("0 available-balance failure(s)", output, "level 1")
        check.is_in("0 budget-chain failure(s)", output, "level 3")

        # $9,000 (Unallocated) - $200 (Groceries), nothing pending.
        account = broken_chain.account
        account.refresh_from_db()
        check.equal(account.posted_balance, Money("8800.00", "USD"), "posted")
        check.equal(
            account.available_balance, Money("8800.00", "USD"), "available"
        )

        # payroll1 is now the first link after the chain's baseline.
        payroll1_alloc = TransactionAllocation.objects.get(
            transaction=broken_chain.payroll1, budget=broken_chain.unallocated
        )
        check.equal(
            payroll1_alloc.budget_balance,
            Money("6000.00", "USD"),
            "payroll1 snapshot repaired",
        )
