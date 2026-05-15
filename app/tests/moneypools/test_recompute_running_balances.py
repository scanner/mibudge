"""Tests for the recompute_running_balances management command."""

# system imports
from collections.abc import Callable
from datetime import UTC, datetime
from io import StringIO

# 3rd party imports
import pytest
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
from moneypools.service import budget as budget_svc
from moneypools.service import (
    transaction_allocation as transaction_allocation_svc,
)

pytestmark = pytest.mark.django_db


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
    def test_recompute_fixes_chain_broken_by_orm_delete(
        self,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
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
        # ── Step 1: account + budgets ─────────────────────────────────
        # bank_account_svc auto-creates the Unallocated budget on creation.
        account = bank_account_factory()
        unallocated = account.unallocated_budget
        assert unallocated is not None

        groceries = budget_svc.create(
            bank_account=account,
            name="Groceries",
            budget_type=Budget.BudgetType.CAPPED,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money("500.00", "USD"),
            funding_amount=Money("100.00", "USD"),
        )

        # ── Step 2: three payrolls on distinct dates ──────────────────
        # transaction_svc.create seeds a default Unallocated allocation
        # for each.  After all three, Unallocated holds:
        #   payroll1 alloc: amount=+3000, snapshot=3000
        #   payroll2 alloc: amount=+3000, snapshot=6000
        #   payroll3 alloc: amount=+3000, snapshot=9000
        payroll1 = transaction_factory(
            bank_account=account,
            amount=Money("3000.00", "USD"),
            posted_date=datetime(2026, 1, 15, tzinfo=UTC),
            raw_description="PAYROLL DIRECT DEPOSIT",
        )
        payroll2 = transaction_factory(
            bank_account=account,
            amount=Money("3000.00", "USD"),
            posted_date=datetime(2026, 2, 15, tzinfo=UTC),
            raw_description="PAYROLL DIRECT DEPOSIT",
        )
        _payroll3 = transaction_factory(
            bank_account=account,
            amount=Money("3000.00", "USD"),
            posted_date=datetime(2026, 3, 15, tzinfo=UTC),
            raw_description="PAYROLL DIRECT DEPOSIT",
        )

        # ── Step 3: expense reallocated from Unallocated to Groceries ─
        # transaction_svc creates the default Unallocated allocation; we
        # immediately move it so Groceries reflects the spend and
        # Unallocated stays clean (no expense alloc there).
        expense = transaction_factory(
            bank_account=account,
            amount=Money("-200.00", "USD"),
            posted_date=datetime(2026, 3, 20, tzinfo=UTC),
            raw_description="GROCERY STORE PURCHASE",
        )
        unalloc_expense_alloc = TransactionAllocation.objects.get(
            transaction=expense, budget=unallocated
        )
        transaction_allocation_svc.delete(unalloc_expense_alloc)
        transaction_allocation_svc.create(
            transaction=expense,
            budget=groceries,
            amount=Money("-200.00", "USD"),
        )

        # ── Step 4: baseline is clean ─────────────────────────────────
        # Unallocated.balance=$9,000; Groceries.balance=-$200;
        # posted_balance=$8,800 = sum(budget balances).  All chains OK.
        out = StringIO()
        call_command("verify_balances", stdout=out)
        assert "FAIL" not in out.getvalue(), "Expected a clean baseline"

        # ── Step 5: ORM-delete the middle payroll ─────────────────────
        # Emulates a Django admin delete: Transaction.delete() cascades
        # to remove the Unallocated allocation row, but does NOT call the
        # service layer, so budget.balance and posted_balance are NOT
        # decremented.  After the delete:
        #   - Unallocated.balance stays $9,000   (should be $6,000)
        #   - posted_balance stays $8,800         (should be $5,800)
        #   - Remaining Unallocated allocs: payroll1 (snap=$3,000)
        #                                   payroll3 (snap=$9,000)
        # The two balances are inflated by the same $3,000 so the
        # account-level (Level 1) check still passes, but the chain
        # (Level 3) is broken: walking forward from the recomputed
        # baseline ($9,000 - $6,000 remaining allocs = $3,000) gives
        # $3,000 + $3,000 = $6,000 for payroll1's slot, yet the stored
        # snapshot is $3,000.
        Transaction.objects.filter(pk=payroll2.pk).delete()

        # ── Step 6: also corrupt the account balance fields ───────────
        # After the ORM delete, both posted_balance and
        # sum(budget.balance) are inflated by the same $3,000, so the
        # Level 1 check would still pass on its own.  Corrupt them here
        # to simulate the realistic case where balance drift accumulates
        # independently (e.g. a separate bulk import or admin action).
        # This ensures the test exercises _recompute_account_balance, not
        # just the snapshot chain repair.
        BankAccount.objects.filter(pk=account.pk).update(
            posted_balance=Money("99999.00", "USD"),
            available_balance=Money("99999.00", "USD"),
        )

        # ── Step 7: verify_balances reports both failures ─────────────
        # Level 1 fails: posted_balance ($99,999) ≠ sum(budget.balance) ($8,800).
        # Level 3 fails: payroll1's snapshot ($3,000) does not match the
        # expected running value ($6,000) with payroll2's alloc absent.
        out = StringIO()
        with pytest.raises(CommandError):
            call_command("verify_balances", stdout=out)
        output = out.getvalue()
        assert "1 account-level failure(s)" in output
        assert "1 budget-chain failure(s)" in output
        assert unallocated.name in output

        # ── Step 8: recompute_running_balances repairs everything ─────
        # (a) Rewalks each budget's allocation chain from the earliest
        #     allocation and rewrites budget_balance snapshots to be
        #     self-consistent with the current budget.balance.
        # (b) Recomputes posted_balance and available_balance as
        #     sum(budget.balance) − sum(pending-tx amounts).
        # After the recompute both account balances equal $8,800
        # (Unallocated $9,000 + Groceries −$200; no pending transactions).
        err = StringIO()
        call_command("recompute_running_balances", stderr=err)

        # ── Step 9: verify_balances is clean after recomputation ──────
        out = StringIO()
        call_command("verify_balances", stdout=out)
        output = out.getvalue()
        assert "FAIL" not in output
        assert "0 account-level failure(s)" in output
        assert "0 budget-chain failure(s)" in output

        # posted_balance and available_balance are fixed to match
        # sum(budget.balance) = $9,000 (Unallocated) − $200 (Groceries).
        account.refresh_from_db()
        assert account.posted_balance == Money("8800.00", "USD")
        assert account.available_balance == Money("8800.00", "USD")

        # Payroll1's snapshot is updated from $3,000 to $6,000: the correct
        # running value once payroll2's alloc is no longer in the chain.
        payroll1_alloc = TransactionAllocation.objects.get(
            transaction=payroll1, budget=unallocated
        )
        assert payroll1_alloc.budget_balance == Money("6000.00", "USD")
