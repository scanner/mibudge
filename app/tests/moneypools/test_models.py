"""Tests for moneypools models and their signal-driven balance logic."""

# system imports
#
from collections.abc import Callable

# 3rd party imports
#
import pytest
from moneyed import USD, Money

# app imports
#
from moneypools.models import (
    BankAccount,
    Budget,
    InternalTransaction,
    Transaction,
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
    """Tests for Transaction creation, updates, and deletion."""

    ####################################################################
    #
    def test_create_updates_available_balance_and_unallocated_budget(
        self,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
    ) -> None:
        """
        GIVEN: a bank account with known available and posted balances
        WHEN:  a pending transaction is created against it
        THEN:  the available balance decreases by the transaction amount,
               the posted balance is unchanged, and the unallocated budget
               reflects the new available balance
        """
        BANK_AVAIL_BAL = 900
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

        assert transaction.bank_account.available_balance == Money(
            BANK_AVAIL_BAL + TRANSACTION_AMT, USD
        )
        assert transaction.bank_account.posted_balance == Money(
            BANK_POSTED_BAL, USD
        )
        assert transaction.budget is not None
        assert transaction.budget_balance == transaction.budget.balance
        assert bank_account.unallocated_budget is not None
        assert (
            bank_account.unallocated_budget.balance
            == bank_account.available_balance
        )
        assert transaction.budget == bank_account.unallocated_budget

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
        THEN:  the posted balance decreases by the transaction amount;
               the available balance and unallocated budget are unchanged
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
        assert ba.unallocated_budget is not None
        assert ba.unallocated_budget.balance == ba.available_balance

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
        assert ba.unallocated_budget is not None
        assert ba.unallocated_budget.balance == ba.available_balance

    ####################################################################
    #
    def test_amount_change_updates_all_balances(
        self,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
    ) -> None:
        """
        GIVEN: a pending transaction with an initial amount (e.g. a petrol
               pre-auth hold that later settles at a different amount)
        WHEN:  the transaction amount is updated and it is marked as posted
        THEN:  the bank account's available and posted balances and the budget
               snapshot all reflect the final settled amount
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

        assert upd_trans.budget is not None
        assert ba.unallocated_budget is not None
        assert upd_trans.budget_balance == upd_trans.budget.balance
        assert ba.unallocated_budget.balance == ba.available_balance
        assert upd_trans.budget == ba.unallocated_budget
        assert upd_trans.bank_account.available_balance == Money(
            BANK_AVAIL_BAL + FINAL_AMT, USD
        )
        assert upd_trans.bank_account.posted_balance == Money(
            BANK_POSTED_BAL + FINAL_AMT, USD
        )
        assert ba.available_balance == Money(BANK_AVAIL_BAL + FINAL_AMT, USD)
        assert ba.posted_balance == Money(BANK_POSTED_BAL + FINAL_AMT, USD)

    ####################################################################
    #
    def test_budget_reassignment_moves_balance_between_budgets(
        self,
        bank_account_factory: Callable[..., BankAccount],
        budget_factory: Callable[..., Budget],
        transaction_factory: Callable[..., Transaction],
        internal_transaction_factory: Callable[..., InternalTransaction],
    ) -> None:
        """
        GIVEN: a transaction initially assigned to the unallocated budget, and
               a destination budget funded to cover the transaction amount
        WHEN:  the transaction is reassigned to the destination budget and posted
        THEN:  the destination budget balance drops to zero, the unallocated
               budget retains the posted-balance remainder, and the bank account
               balances reflect the posted transaction
        """
        BANK_AVAIL_BAL = 1000
        BANK_POSTED_BAL = 1000
        TRANSACTION_AMT = -100

        bank_account = bank_account_factory(
            available_balance=BANK_AVAIL_BAL, posted_balance=BANK_POSTED_BAL
        )
        dst_budget = budget_factory(balance=0)
        it = internal_transaction_factory(
            amount=abs(TRANSACTION_AMT),
            src_budget=bank_account.unallocated_budget,
            dst_budget=dst_budget,
        )
        assert it.amount == Money(abs(TRANSACTION_AMT), USD)
        assert dst_budget.balance == Money(abs(TRANSACTION_AMT), USD)

        transaction = transaction_factory(
            amount=TRANSACTION_AMT,
            pending=True,
            raw_description="This is a transaction",
            bank_account=bank_account,
        )
        transaction.save()

        upd_trans = Transaction.objects.get(id=transaction.id)
        upd_trans.budget = dst_budget
        upd_trans.pending = False
        upd_trans.save()

        ba = BankAccount.objects.get(id=bank_account.id)
        dst_budget = Budget.objects.get(id=dst_budget.id)

        assert ba.unallocated_budget is not None
        assert ba.unallocated_budget.balance == Money(
            BANK_POSTED_BAL + TRANSACTION_AMT, USD
        )
        assert dst_budget.balance == Money(0, USD)
        assert ba.posted_balance == Money(
            BANK_POSTED_BAL + TRANSACTION_AMT, USD
        )
        assert ba.available_balance == Money(
            BANK_AVAIL_BAL + TRANSACTION_AMT, USD
        )

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
