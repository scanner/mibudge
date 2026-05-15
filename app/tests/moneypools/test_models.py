"""Tests for moneypools models and their balance logic."""

# system imports
#
from collections.abc import Callable
from datetime import UTC, datetime

# 3rd party imports
#
import pytest
from django.core.exceptions import ValidationError
from moneyed import USD, Money

from moneypools.models import (
    BankAccount,
    Budget,
    InternalTransaction,
    Transaction,
    TransactionAllocation,
)
from moneypools.service import budget as budget_svc
from moneypools.service import internal_transaction as internal_transaction_svc
from moneypools.service import transaction as transaction_svc
from moneypools.service import (
    transaction_allocation as transaction_allocation_svc,
)
from users.models import User

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
            # Goal: complete is driven by funded_amount in the ITX service,
            # not by the pre_save signal.
            ("G", 200, False),
            ("G", 100, False),
            ("R", 200, True),
            ("R", 100, False),
            # Capped: complete is never set by the signal; funding engine uses
            # the balance/target gap directly.
            ("C", 200, False),
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
        THEN:  complete matches expected_complete (Capped is always False)
        """
        budget = budget_factory(
            balance=balance, target_balance=200, budget_type=budget_type
        )
        assert budget.complete is expected_complete

    ####################################################################
    #
    def test_fillup_budget_created_for_recurring(
        self,
        budget_factory: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: a Recurring budget
        WHEN:  the budget is saved
        THEN:  an associated type-A fill-up budget is created and linked
        """
        budget = budget_factory(budget_type="R")
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
        user_factory: Callable[..., User],
    ) -> None:
        """
        GIVEN: a Recurring budget with an associated fill-up goal
        WHEN:  the parent budget is deleted via BudgetService.delete
        THEN:  the fill-up goal budget is also deleted
        """
        budget = budget_factory(budget_type="R", balance=0)
        budget.refresh_from_db()
        fillup_id = budget.fillup_goal_id
        assert fillup_id is not None

        actor = user_factory()
        budget_svc.delete(budget, actor=actor)

        assert not Budget.objects.filter(id=fillup_id).exists()

    ####################################################################
    #
    def test_complete_stays_set_after_spending_for_goal(
        self,
        budget_factory: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: a Goal budget whose complete flag was set by the ITX service
        WHEN:  the balance drops below the target via spending
        THEN:  complete remains True (sticky high-water-mark latch)
        """
        budget = budget_factory(
            balance=200, target_balance=200, budget_type="G"
        )
        # complete is set by the ITX service (funded_amount path), not the
        # signal, so force it here to represent a post-funding state.
        Budget.objects.filter(pkid=budget.pkid).update(complete=True)
        budget.refresh_from_db()

        budget.balance = Money(100, USD)
        budget.save()
        budget.refresh_from_db()
        assert budget.complete is True


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

        internal_transaction_svc.delete(it)

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
        transaction_svc.update(upd_trans, pending=False)

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

        upd_trans = Transaction.objects.get(id=transaction.id)
        transaction_svc.update(
            upd_trans, amount=Money(FINAL_AMT, USD), pending=False
        )

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
        transaction_svc.delete(transaction)

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
        alloc.refresh_from_db()
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
        # transaction_factory seeds a default allocation to unallocated.
        alloc = TransactionAllocation.objects.get(transaction=txn)
        assert alloc.budget == bank_account.unallocated_budget

        # Reassign the allocation to the destination budget via the service
        transaction_allocation_svc.delete(alloc)
        transaction_allocation_svc.create(
            transaction=txn,
            budget=dst_budget,
            amount=Money(TRANSACTION_AMT, USD),
        )

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

        transaction_allocation_svc.delete(alloc)

        budget = Budget.objects.get(id=budget.id)
        assert budget.balance == Money(BUDGET_BAL, USD)

    ####################################################################
    #
    def test_amount_change_adjusts_budget_balance(
        self,
        bank_account_factory: Callable[..., BankAccount],
        budget_factory: Callable[..., Budget],
        transaction_factory: Callable[..., Transaction],
        transaction_allocation_factory: Callable[..., TransactionAllocation],
    ) -> None:
        """
        GIVEN: a -100 allocation against a budget with $500 balance
        WHEN:  the allocation amount is changed to -60
        THEN:  the budget balance reflects the delta (+40)
        """
        BUDGET_BAL = 500
        OLD_AMT = -100
        NEW_AMT = -60

        budget = budget_factory(balance=BUDGET_BAL)
        bank_account = bank_account_factory(available_balance=1000)
        txn = transaction_factory(
            amount=OLD_AMT,
            raw_description="Test purchase",
            bank_account=bank_account,
        )
        alloc = transaction_allocation_factory(
            transaction=txn, budget=budget, amount=OLD_AMT
        )
        assert budget.balance == Money(BUDGET_BAL + OLD_AMT, USD)

        transaction_allocation_svc.update_amount(alloc, Money(NEW_AMT, USD))

        budget = Budget.objects.get(id=budget.id)
        assert budget.balance == Money(BUDGET_BAL + NEW_AMT, USD)

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
        # 3 total: 1 default to unallocated (seeded by transaction_svc.create)
        # + 2 explicit allocations added by this test.
        assert txn.allocations.count() == 3

    ####################################################################
    #
    @pytest.mark.parametrize(
        ("early_date", "late_date"),
        [
            (
                datetime(2026, 4, 8, tzinfo=UTC),
                datetime(2026, 4, 10, tzinfo=UTC),
            ),
            (
                datetime(2026, 4, 8, tzinfo=UTC),
                datetime(2026, 4, 8, tzinfo=UTC),
            ),
        ],
        ids=["different-dates", "same-date"],
    )
    def test_out_of_order_allocation_corrects_running_balances(
        self,
        bank_account_factory: Callable[..., BankAccount],
        budget_factory: Callable[..., Budget],
        transaction_factory: Callable[..., Transaction],
        transaction_allocation_factory: Callable[..., TransactionAllocation],
        early_date: datetime,
        late_date: datetime,
    ) -> None:
        """
        GIVEN: a budget with $500 and two transactions
        WHEN:  the chronologically later allocation is created first
        THEN:  budget_balance snapshots reflect chronological order,
               not creation order — first shows $340, second shows
               $180

        When both transactions share a date, chronological order is
        determined by transaction.created_at (creation order).
        """
        bank_account = bank_account_factory(available_balance=2000)
        budget = budget_factory(
            bank_account=bank_account,
            balance=Money(500, USD),
        )

        # Create earlier_tx first so it gets the earlier created_at.
        # For same-date ties, created_at determines chronological
        # order.
        earlier_tx = transaction_factory(
            bank_account=bank_account,
            amount=Money(-160, USD),
            posted_date=early_date,
            raw_description="Check 322",
        )
        later_tx = transaction_factory(
            bank_account=bank_account,
            amount=Money(-160, USD),
            posted_date=late_date,
            raw_description="Check 323",
        )

        # Allocate the later transaction first (out of order).
        transaction_allocation_factory(
            transaction=later_tx,
            budget=budget,
            amount=Money(-160, USD),
        )
        # Then allocate the earlier one.
        transaction_allocation_factory(
            transaction=earlier_tx,
            budget=budget,
            amount=Money(-160, USD),
        )

        alloc_early = TransactionAllocation.objects.get(
            transaction=earlier_tx, budget=budget
        )
        alloc_late = TransactionAllocation.objects.get(
            transaction=later_tx, budget=budget
        )

        # Chronologically first: 500 - 160 = 340
        assert alloc_early.budget_balance == Money(340, USD)
        # Chronologically second: 340 - 160 = 180
        assert alloc_late.budget_balance == Money(180, USD)

    ####################################################################
    #
    def test_mid_insert_only_updates_subsequent_balances(
        self,
        bank_account_factory: Callable[..., BankAccount],
        budget_factory: Callable[..., Budget],
        transaction_factory: Callable[..., Transaction],
        transaction_allocation_factory: Callable[..., TransactionAllocation],
    ) -> None:
        """
        GIVEN: 21 transactions spread across 3 days, with the middle one
               initially unallocated
        WHEN:  1) 20 transactions are allocated (skipping the middle),
                  and running balances are verified;
               2) the middle transaction is then allocated, and running
                  balances are verified;
               3) the transaction immediately after the middle has its
                  allocation moved to the unallocated budget, and running
                  balances are verified
        THEN:  budget_balance snapshots are correct at each stage
        """
        bank_account = bank_account_factory(available_balance=50000)
        budget = budget_factory(
            bank_account=bank_account,
            balance=Money(10000, USD),
        )
        unallocated = bank_account.unallocated_budget

        # 21 transactions: 7 on each of 3 days.  Each is a -100 debit.
        days = [
            datetime(2026, 4, 6, tzinfo=UTC),
            datetime(2026, 4, 7, tzinfo=UTC),
            datetime(2026, 4, 8, tzinfo=UTC),
        ]
        txns: list[Transaction] = []
        for day in days:
            for i in range(7):
                txns.append(
                    transaction_factory(
                        bank_account=bank_account,
                        amount=Money(-100, USD),
                        posted_date=day,
                        raw_description=f"Tx {day.day}-{i}",
                    )
                )
        assert len(txns) == 21

        # txns[10] is the middle transaction (0-based index 10 of 21).
        mid_idx = 10
        after_mid_idx = mid_idx + 1

        def assert_running_balances() -> None:
            """Re-fetch all budget allocations and verify running balances."""
            budget.refresh_from_db()
            allocs = list(
                TransactionAllocation.objects.filter(budget=budget)
                .order_by(
                    "transaction__transaction_date",
                    "transaction__created_at",
                    "created_at",
                )
                .select_related("transaction")
            )
            total = sum(a.amount.amount for a in allocs)
            running = budget.balance.amount - total
            for a in allocs:
                running += a.amount.amount
                assert a.budget_balance.amount == running, (
                    f"Allocation {a.pk} (tx date "
                    f"{a.transaction.transaction_date}): "
                    f"expected {running}, got {a.budget_balance.amount}"
                )

        # --- Phase 1: allocate all 20 transactions except the middle ---
        for i, tx in enumerate(txns):
            if i == mid_idx:
                continue
            transaction_allocation_factory(
                transaction=tx,
                budget=budget,
                amount=Money(-100, USD),
            )

        assert TransactionAllocation.objects.filter(budget=budget).count() == 20
        assert_running_balances()

        # --- Phase 2: allocate the middle transaction ---
        transaction_allocation_factory(
            transaction=txns[mid_idx],
            budget=budget,
            amount=Money(-100, USD),
        )

        assert TransactionAllocation.objects.filter(budget=budget).count() == 21
        assert_running_balances()

        # --- Phase 3: move the allocation after the middle to the
        #              unallocated budget (simulates removing a
        #              transaction from a budget) ---
        alloc_to_move = TransactionAllocation.objects.get(
            transaction=txns[after_mid_idx],
            budget=budget,
        )
        transaction_allocation_svc.delete(alloc_to_move)
        transaction_allocation_svc.create(
            transaction=txns[after_mid_idx],
            budget=unallocated,
            amount=Money(-100, USD),
        )

        assert TransactionAllocation.objects.filter(budget=budget).count() == 20
        assert_running_balances()

    ####################################################################
    #
    def test_internal_transaction_between_allocations(
        self,
        bank_account_factory: Callable[..., BankAccount],
        budget_factory: Callable[..., Budget],
        transaction_factory: Callable[..., Transaction],
        transaction_allocation_factory: Callable[..., TransactionAllocation],
        internal_transaction_factory: Callable[..., InternalTransaction],
    ) -> None:
        """
        GIVEN: a budget at $0, funded to $500 via InternalTransaction,
               then two -$100 allocations
        WHEN:  a second InternalTransaction adds $200 and a third
               allocation of -$100 is created
        THEN:  the third allocation's budget_balance reflects the
               top-up: (500 - 100 - 100) + 200 - 100 = 400,
               not (500 - 100 - 100 - 100) = 200
        """
        account = bank_account_factory(
            available_balance=Money(5000, USD),
            posted_balance=Money(5000, USD),
        )
        unalloc = account.unallocated_budget
        assert unalloc is not None
        budget = budget_factory(bank_account=account, balance=Money(0, USD))

        # Fund the budget: +$500.
        # effective_date = Jan 1 midnight so it slots before any Jan 1 tx.
        internal_transaction_factory(
            bank_account=account,
            src_budget=unalloc,
            dst_budget=budget,
            amount=Money(500, USD),
            effective_date=datetime(2024, 1, 1, tzinfo=UTC),
        )
        budget.refresh_from_db()
        assert budget.balance == Money(500, USD)

        # Two allocations before the top-up.
        tx1 = transaction_factory(
            bank_account=account,
            amount=Money(-100, USD),
            posted_date=datetime(2024, 1, 1, tzinfo=UTC),
        )
        a1 = transaction_allocation_factory(
            transaction=tx1,
            budget=budget,
            amount=Money(-100, USD),
        )

        tx2 = transaction_factory(
            bank_account=account,
            amount=Money(-100, USD),
            posted_date=datetime(2024, 1, 2, tzinfo=UTC),
        )
        a2 = transaction_allocation_factory(
            transaction=tx2,
            budget=budget,
            amount=Money(-100, USD),
        )

        a1.refresh_from_db()
        a2.refresh_from_db()
        assert a1.budget_balance == Money(400, USD)
        assert a2.budget_balance == Money(300, USD)

        # Mid-stream top-up: +$200 -> budget now $500.
        # effective_date = Jan 3 midnight so it slots after tx2 (Jan 2)
        # and is captured in tx3's window (Jan 3).
        budget.refresh_from_db()
        assert budget.balance == Money(300, USD)
        unalloc.refresh_from_db()

        internal_transaction_factory(
            bank_account=account,
            src_budget=unalloc,
            dst_budget=budget,
            amount=Money(200, USD),
            effective_date=datetime(2024, 1, 3, tzinfo=UTC),
        )
        budget.refresh_from_db()
        assert budget.balance == Money(500, USD)

        # Third allocation after the top-up.
        tx3 = transaction_factory(
            bank_account=account,
            amount=Money(-100, USD),
            posted_date=datetime(2024, 1, 3, tzinfo=UTC),
        )
        a3 = transaction_allocation_factory(
            transaction=tx3,
            budget=budget,
            amount=Money(-100, USD),
        )

        budget.refresh_from_db()
        assert budget.balance == Money(400, USD)

        # The prior two should be unchanged.
        a1.refresh_from_db()
        a2.refresh_from_db()
        assert a1.budget_balance == Money(400, USD)
        assert a2.budget_balance == Money(300, USD)

        # The third must reflect the +$200 top-up:
        # 300 + 200 - 100 = 400, not 300 - 100 = 200.
        a3.refresh_from_db()
        assert a3.budget_balance == Money(400, USD), (
            f"Expected budget_balance=$400 (reflecting +$200 "
            f"top-up), got {a3.budget_balance}"
        )
