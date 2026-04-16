"""Tests for moneypools models and their signal-driven balance logic."""

# system imports
#
from collections.abc import Callable

# 3rd party imports
#
import pytest
from django.core.exceptions import ValidationError
from moneyed import USD, Money

# app imports
#
from moneypools.models import (
    BankAccount,
    Budget,
    InternalTransaction,
    Transaction,
    TransactionAllocation,
)

pytestmark = pytest.mark.django_db


########################################################################
########################################################################
#
class TestBankAccount:
    """Tests for BankAccount creation and auto-created unallocated budget."""

    ####################################################################
    #
    def test_unallocated_budget_created_on_save(
        self, bank_account_factory: Callable[..., BankAccount]
    ) -> None:
        """
        GIVEN: a newly created bank account
        WHEN:  the account is inspected
        THEN:  an unallocated budget exists and is linked back to the account
        """
        bank_account = bank_account_factory()
        assert bank_account.unallocated_budget
        assert bank_account.unallocated_budget.bank_account == bank_account

    ####################################################################
    #
    def test_balances_reflect_factory_values(
        self, bank_account_factory: Callable[..., BankAccount]
    ) -> None:
        """
        GIVEN: a bank account created with explicit available and posted balances
        WHEN:  the account is inspected
        THEN:  the monetary fields match the values passed to the factory
        """
        bank_account = bank_account_factory(
            available_balance=900, posted_balance=1000
        )
        assert bank_account.posted_balance == Money(1000, USD)
        assert bank_account.available_balance == Money(900, USD)


########################################################################
########################################################################
#
class TestBudget:
    """Tests for Budget signal-driven complete flag logic."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "budget_type,balance,expected_complete",
        [
            ("G", 200, True),
            ("G", 100, False),
            ("R", 200, True),
            ("R", 100, False),
            ("C", 200, True),
            ("C", 100, False),
        ],
    )
    def test_complete_flag_on_save(
        self,
        budget_type: str,
        balance: int,
        expected_complete: bool,
        budget_factory: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: a budget of the given type with the given balance vs. a 200 target
        WHEN:  the budget is saved
        THEN:  complete matches expected_complete
        """
        budget = budget_factory(
            balance=balance, target_balance=200, budget_type=budget_type
        )
        assert budget.complete is expected_complete

    ####################################################################
    #
    def test_fillup_budget_created_for_recurring_with_fillup_goal(
        self,
        budget_factory: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: a Recurring budget created with with_fillup_goal=True
        WHEN:  the budget is saved
        THEN:  an associated type-A fill-up budget is created and linked
        """
        budget = budget_factory(budget_type="R", with_fillup_goal=True)
        budget.refresh_from_db()
        assert budget.fillup_goal is not None
        fillup = budget.fillup_goal
        assert fillup.budget_type == "A"
        assert fillup.name == f"{budget.name} Fill-up"
        assert fillup.bank_account == budget.bank_account

    ####################################################################
    #
    def test_fillup_budget_deleted_when_parent_deleted(
        self,
        budget_factory: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: a Recurring budget with an associated fill-up goal
        WHEN:  the parent budget is deleted
        THEN:  the fill-up goal budget is also deleted
        """
        budget = budget_factory(budget_type="R", with_fillup_goal=True)
        budget.refresh_from_db()
        fillup_id = budget.fillup_goal_id
        assert fillup_id is not None

        budget.delete()

        assert not Budget.objects.filter(id=fillup_id).exists()

    ####################################################################
    #
    @pytest.mark.parametrize(
        "budget_type,expected_complete_after_spend",
        [
            # Goal: stays complete once funded regardless of spending.
            ("G", True),
            # Capped: recomputed on every save, so spending clears it.
            ("C", False),
        ],
    )
    def test_complete_after_spending(
        self,
        budget_type: str,
        expected_complete_after_spend: bool,
        budget_factory: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: a budget at its target (complete=True)
        WHEN:  the balance drops below the target
        THEN:  complete reflects the type's clearing semantics
               (Goal stays True; Capped reverts to False)
        """
        budget = budget_factory(
            balance=200, target_balance=200, budget_type=budget_type
        )
        assert budget.complete is True

        budget.balance = Money(100, USD)
        budget.save()
        budget.refresh_from_db()
        assert budget.complete is expected_complete_after_spend


########################################################################
########################################################################
#
class TestInternalTransaction:
    """Tests for InternalTransaction creation, updates, and deletion."""

    ####################################################################
    #
    def test_create_transfers_balance_between_budgets(
        self,
        budget_factory: Callable[..., Budget],
        internal_transaction_factory: Callable[..., InternalTransaction],
    ) -> None:
        """
        GIVEN: two budgets each with a balance of 100
        WHEN:  a 50-unit internal transaction is created between them
        THEN:  src balance decreases by 50, dst balance increases by 50, and
               the snapshot fields capture the post-transfer balances
        """
        src_budget = budget_factory(balance=100)
        dst_budget = budget_factory(balance=100)

        it = internal_transaction_factory(
            amount=50, src_budget=src_budget, dst_budget=dst_budget
        )

        assert src_budget.balance == Money(50, USD)
        assert dst_budget.balance == Money(150, USD)
        assert it.src_budget_balance == Money(50, USD)
        assert it.dst_budget_balance == Money(150, USD)

    ####################################################################
    #
    def test_same_src_dst_budget_raises_validation_error(
        self,
        budget_factory: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: an InternalTransaction with the same budget as both src and dst
        WHEN:  clean() is called
        THEN:  a ValidationError is raised
        """
        budget = budget_factory(balance=100)
        it = InternalTransaction(src_budget=budget, dst_budget=budget)
        with pytest.raises(ValidationError):
            it.clean()

    ####################################################################
    #
    def test_negative_amount_raises(
        self,
        budget_factory: Callable[..., Budget],
        internal_transaction_factory: Callable[..., InternalTransaction],
    ) -> None:
        """
        GIVEN: two budgets
        WHEN:  an internal transaction with a negative amount is attempted
        THEN:  a ValueError is raised
        """
        src_budget = budget_factory(balance=100)
        dst_budget = budget_factory(balance=100)

        with pytest.raises(ValueError):
            internal_transaction_factory(
                amount=-50, src_budget=src_budget, dst_budget=dst_budget
            )

    ####################################################################
    #
    def test_amount_update_adjusts_balances(
        self,
        budget_factory: Callable[..., Budget],
        internal_transaction_factory: Callable[..., InternalTransaction],
    ) -> None:
        """
        GIVEN: an internal transaction of 50 between two budgets each starting at 100
        WHEN:  the transaction amount is updated to 75
        THEN:  both budget balances and snapshot fields reflect the new amount
        """
        START_BAL = 100
        INITIAL_AMT = 50
        UPDATED_AMT = 75

        src_budget = budget_factory(balance=START_BAL)
        dst_budget = budget_factory(balance=START_BAL)
        it = internal_transaction_factory(
            amount=INITIAL_AMT, src_budget=src_budget, dst_budget=dst_budget
        )

        it.amount = UPDATED_AMT
        it.save()

        src_budget = Budget.objects.get(id=src_budget.id)
        dst_budget = Budget.objects.get(id=dst_budget.id)

        assert src_budget.balance == Money(START_BAL - UPDATED_AMT, USD)
        assert dst_budget.balance == Money(START_BAL + UPDATED_AMT, USD)
        assert it.src_budget_balance == Money(START_BAL - UPDATED_AMT, USD)
        assert it.dst_budget_balance == Money(START_BAL + UPDATED_AMT, USD)

    ####################################################################
    #
    def test_budget_reassignment_adjusts_balances(
        self,
        budget_factory: Callable[..., Budget],
        internal_transaction_factory: Callable[..., InternalTransaction],
    ) -> None:
        """
        GIVEN: an internal transaction between budgets A, and a second pair of
               budgets B
        WHEN:  the transaction's src and dst are reassigned to budgets B, then
               src is reassigned back to A
        THEN:  budgets B reflect the full transfer, and budget A's balance
               accounts for the partial reassignment
        """
        START_BAL_A = 100
        START_BAL_B = 325
        TRANSACTION_AMT = 50

        src_a = budget_factory(balance=START_BAL_A)
        dst_a = budget_factory(balance=START_BAL_A)
        it = internal_transaction_factory(
            amount=TRANSACTION_AMT, src_budget=src_a, dst_budget=dst_a
        )

        src_b = budget_factory(balance=START_BAL_B)
        dst_b = budget_factory(balance=START_BAL_B)

        it.src_budget = src_b
        it.dst_budget = dst_b
        it.save()

        src_b = Budget.objects.get(id=src_b.id)
        dst_b = Budget.objects.get(id=dst_b.id)
        assert src_b.balance == Money(START_BAL_B - TRANSACTION_AMT, USD)
        assert dst_b.balance == Money(START_BAL_B + TRANSACTION_AMT, USD)

        it.src_budget = src_a
        it.save()

        src_a = Budget.objects.get(id=src_a.id)
        dst_b = Budget.objects.get(id=dst_b.id)
        assert src_a.balance == Money(START_BAL_A - TRANSACTION_AMT, USD)
        assert dst_b.balance == Money(START_BAL_B + TRANSACTION_AMT, USD)

    ####################################################################
    #
    def test_delete_restores_balances(
        self,
        budget_factory: Callable[..., Budget],
        internal_transaction_factory: Callable[..., InternalTransaction],
    ) -> None:
        """
        GIVEN: a 50-unit internal transaction between two budgets each starting at 100
        WHEN:  the transaction is deleted
        THEN:  both budget balances return to their original values
        """
        src_budget = budget_factory(balance=100)
        dst_budget = budget_factory(balance=100)
        it = internal_transaction_factory(
            amount=50, src_budget=src_budget, dst_budget=dst_budget
        )
        assert src_budget.balance == Money(50, USD)
        assert dst_budget.balance == Money(150, USD)

        it.delete()

        src_budget = Budget.objects.get(id=src_budget.id)
        dst_budget = Budget.objects.get(id=dst_budget.id)
        assert src_budget.balance == Money(100, USD)
        assert dst_budget.balance == Money(100, USD)


########################################################################
########################################################################
#
class TestTransaction:
    """Tests for Transaction creation, updates, and deletion.

    Transaction signals handle only bank account balances. Budget
    balance logic is tested in TestTransactionAllocation.
    """

    ####################################################################
    #
    def test_create_pending_updates_available_not_posted(
        self,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
    ) -> None:
        """
        GIVEN: a bank account with known available and posted balances
        WHEN:  a pending transaction is created against it
        THEN:  the available balance changes by the transaction amount,
               the posted balance is unchanged
        """
        BANK_AVAIL_BAL = 900
        BANK_POSTED_BAL = 1000
        TRANSACTION_AMT = -100

        bank_account = bank_account_factory(
            available_balance=BANK_AVAIL_BAL, posted_balance=BANK_POSTED_BAL
        )
        transaction_factory(
            amount=TRANSACTION_AMT,
            pending=True,
            raw_description="This is a transaction",
            bank_account=bank_account,
        )

        assert bank_account.available_balance == Money(
            BANK_AVAIL_BAL + TRANSACTION_AMT, USD
        )
        assert bank_account.posted_balance == Money(BANK_POSTED_BAL, USD)

    ####################################################################
    #
    def test_pending_to_posted_updates_posted_balance(
        self,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
    ) -> None:
        """
        GIVEN: a pending transaction against a bank account
        WHEN:  the transaction is marked as no longer pending (posted)
        THEN:  the posted balance changes by the transaction amount;
               the available balance is unchanged
        """
        BANK_AVAIL_BAL = 1000
        BANK_POSTED_BAL = 1000
        TRANSACTION_AMT = -100

        bank_account = bank_account_factory(
            available_balance=BANK_AVAIL_BAL, posted_balance=BANK_POSTED_BAL
        )
        transaction = transaction_factory(
            amount=TRANSACTION_AMT,
            pending=True,
            raw_description="This is a transaction",
            bank_account=bank_account,
        )

        ba = BankAccount.objects.get(id=bank_account.id)
        assert ba.posted_balance == Money(BANK_POSTED_BAL, USD)
        assert ba.available_balance == Money(
            BANK_AVAIL_BAL + TRANSACTION_AMT, USD
        )

        upd_trans = Transaction.objects.get(id=transaction.id)
        upd_trans.pending = False
        upd_trans.save()

        ba = BankAccount.objects.get(id=bank_account.id)
        assert ba.posted_balance == Money(
            BANK_POSTED_BAL + TRANSACTION_AMT, USD
        )
        assert ba.available_balance == Money(
            BANK_AVAIL_BAL + TRANSACTION_AMT, USD
        )

    ####################################################################
    #
    def test_amount_change_updates_bank_account_balances(
        self,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
    ) -> None:
        """
        GIVEN: a pending transaction with an initial amount (e.g. a petrol
               pre-auth hold that later settles at a different amount)
        WHEN:  the transaction amount is updated and it is marked as posted
        THEN:  the bank account's available and posted balances reflect the
               final settled amount
        """
        BANK_AVAIL_BAL = 900
        BANK_POSTED_BAL = 1000
        TRANSACTION_AMT = -100
        FINAL_AMT = -28.43

        bank_account = bank_account_factory(
            available_balance=BANK_AVAIL_BAL, posted_balance=BANK_POSTED_BAL
        )
        transaction = transaction_factory(
            amount=TRANSACTION_AMT,
            pending=True,
            raw_description="This is a transaction",
            bank_account=bank_account,
        )
        transaction.save()

        upd_trans = Transaction.objects.get(id=transaction.id)
        upd_trans.amount = Money(FINAL_AMT, USD)
        upd_trans.pending = False
        upd_trans.save()

        ba = BankAccount.objects.get(id=bank_account.id)
        assert ba.available_balance == Money(BANK_AVAIL_BAL + FINAL_AMT, USD)
        assert ba.posted_balance == Money(BANK_POSTED_BAL + FINAL_AMT, USD)

    ####################################################################
    #
    @pytest.mark.parametrize("pending", [True, False])
    def test_delete_restores_bank_account_balances(
        self,
        pending: bool,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
    ) -> None:
        """
        GIVEN: a bank account with known balances and a transaction against it,
               with pending=True or pending=False
        WHEN:  the transaction is deleted
        THEN:  both the available and posted balances return to their original
               values regardless of the transaction's pending state
        """
        BANK_AVAIL_BAL = 900
        BANK_POSTED_BAL = 1000
        TRANSACTION_AMT = -100

        bank_account = bank_account_factory(
            available_balance=BANK_AVAIL_BAL, posted_balance=BANK_POSTED_BAL
        )
        transaction = transaction_factory(
            amount=TRANSACTION_AMT,
            pending=pending,
            raw_description="This is a transaction",
            bank_account=bank_account,
        )
        transaction.delete()

        ba = BankAccount.objects.get(id=bank_account.id)
        assert ba.posted_balance == Money(BANK_POSTED_BAL, USD)
        assert ba.available_balance == Money(BANK_AVAIL_BAL, USD)


########################################################################
########################################################################
#
class TestTransactionAllocation:
    """Tests for TransactionAllocation signal-driven budget balance logic."""

    ####################################################################
    #
    def test_create_credits_budget(
        self,
        bank_account_factory: Callable[..., BankAccount],
        budget_factory: Callable[..., Budget],
        transaction_factory: Callable[..., Transaction],
        transaction_allocation_factory: Callable[..., TransactionAllocation],
    ) -> None:
        """
        GIVEN: a transaction and a budget with a known balance
        WHEN:  an allocation is created linking the transaction to the budget
        THEN:  the budget balance increases by the allocation amount and the
               balance snapshot is captured
        """
        BUDGET_BAL = 500
        ALLOC_AMT = -100

        bank_account = bank_account_factory(available_balance=1000)
        budget = budget_factory(balance=BUDGET_BAL)
        txn = transaction_factory(
            amount=ALLOC_AMT,
            raw_description="Test purchase",
            bank_account=bank_account,
        )
        alloc = transaction_allocation_factory(
            transaction=txn, budget=budget, amount=ALLOC_AMT
        )

        assert budget.balance == Money(BUDGET_BAL + ALLOC_AMT, USD)
        assert alloc.budget_balance == budget.balance

    ####################################################################
    #
    def test_create_defaults_to_unallocated_budget(
        self,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
        transaction_allocation_factory: Callable[..., TransactionAllocation],
    ) -> None:
        """
        GIVEN: a transaction against a bank account
        WHEN:  an allocation is created with no budget specified
        THEN:  the allocation is assigned to the bank account's unallocated
               budget
        """
        bank_account = bank_account_factory(available_balance=1000)
        txn = transaction_factory(
            amount=-50,
            raw_description="Test purchase",
            bank_account=bank_account,
        )
        alloc = transaction_allocation_factory(
            transaction=txn, budget=None, amount=-50
        )

        assert alloc.budget == bank_account.unallocated_budget

    ####################################################################
    #
    def test_budget_reassignment_moves_balance(
        self,
        bank_account_factory: Callable[..., BankAccount],
        budget_factory: Callable[..., Budget],
        transaction_factory: Callable[..., Transaction],
        transaction_allocation_factory: Callable[..., TransactionAllocation],
        internal_transaction_factory: Callable[..., InternalTransaction],
    ) -> None:
        """
        GIVEN: a transaction allocated to the unallocated budget, and a
               destination budget funded to cover the amount
        WHEN:  the allocation's budget is changed to the destination budget
        THEN:  the unallocated budget balance increases (debit removed) and
               the destination budget balance decreases (debit applied)
        """
        BANK_AVAIL_BAL = 1000
        TRANSACTION_AMT = -100

        bank_account = bank_account_factory(
            available_balance=BANK_AVAIL_BAL, posted_balance=BANK_AVAIL_BAL
        )
        dst_budget = budget_factory(balance=0)

        # Fund the destination budget from unallocated
        internal_transaction_factory(
            amount=abs(TRANSACTION_AMT),
            src_budget=bank_account.unallocated_budget,
            dst_budget=dst_budget,
        )
        assert dst_budget.balance == Money(abs(TRANSACTION_AMT), USD)

        txn = transaction_factory(
            amount=TRANSACTION_AMT,
            raw_description="Test purchase",
            bank_account=bank_account,
        )
        alloc = transaction_allocation_factory(
            transaction=txn, budget=None, amount=TRANSACTION_AMT
        )
        assert alloc.budget == bank_account.unallocated_budget

        # Reassign the allocation to the destination budget
        alloc.budget = dst_budget
        alloc.save()

        assert bank_account.unallocated_budget is not None
        unalloc = Budget.objects.get(id=bank_account.unallocated_budget.id)
        dst_budget = Budget.objects.get(id=dst_budget.id)

        assert dst_budget.balance == Money(0, USD)
        assert unalloc.balance == Money(BANK_AVAIL_BAL + TRANSACTION_AMT, USD)

    ####################################################################
    #
    def test_delete_reverses_budget_balance(
        self,
        bank_account_factory: Callable[..., BankAccount],
        budget_factory: Callable[..., Budget],
        transaction_factory: Callable[..., Transaction],
        transaction_allocation_factory: Callable[..., TransactionAllocation],
    ) -> None:
        """
        GIVEN: a transaction with an allocation against a budget
        WHEN:  the allocation is deleted
        THEN:  the budget balance returns to its pre-allocation value
        """
        BUDGET_BAL = 500
        ALLOC_AMT = -100

        budget = budget_factory(balance=BUDGET_BAL)
        bank_account = bank_account_factory(available_balance=1000)
        txn = transaction_factory(
            amount=ALLOC_AMT,
            raw_description="Test purchase",
            bank_account=bank_account,
        )
        alloc = transaction_allocation_factory(
            transaction=txn, budget=budget, amount=ALLOC_AMT
        )
        assert budget.balance == Money(BUDGET_BAL + ALLOC_AMT, USD)

        alloc.delete()

        budget = Budget.objects.get(id=budget.id)
        assert budget.balance == Money(BUDGET_BAL, USD)

    ####################################################################
    #
    def test_split_transaction_multiple_allocations(
        self,
        bank_account_factory: Callable[..., BankAccount],
        budget_factory: Callable[..., Budget],
        transaction_factory: Callable[..., Transaction],
        transaction_allocation_factory: Callable[..., TransactionAllocation],
    ) -> None:
        """
        GIVEN: a -200 transaction (e.g. a Costco trip with groceries and
               home supplies)
        WHEN:  two allocations are created splitting the amount across two
               budgets
        THEN:  each budget's balance reflects only its portion and the bank
               account balance reflects the full transaction amount
        """
        GROCERIES_BAL = 300
        HOME_BAL = 200
        TOTAL_AMT = -200
        GROCERIES_AMT = -150
        HOME_AMT = -50

        bank_account = bank_account_factory(available_balance=1000)
        groceries_budget = budget_factory(balance=GROCERIES_BAL)
        home_budget = budget_factory(balance=HOME_BAL)

        txn = transaction_factory(
            amount=TOTAL_AMT,
            raw_description="COSTCO WHOLESALE",
            bank_account=bank_account,
        )

        transaction_allocation_factory(
            transaction=txn, budget=groceries_budget, amount=GROCERIES_AMT
        )
        transaction_allocation_factory(
            transaction=txn, budget=home_budget, amount=HOME_AMT
        )

        groceries_budget = Budget.objects.get(id=groceries_budget.id)
        home_budget = Budget.objects.get(id=home_budget.id)

        assert groceries_budget.balance == Money(
            GROCERIES_BAL + GROCERIES_AMT, USD
        )
        assert home_budget.balance == Money(HOME_BAL + HOME_AMT, USD)
        assert txn.allocations.count() == 2
