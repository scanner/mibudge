"""Tests for moneypools models and their balance logic."""

# system imports
#
from collections.abc import Callable
from datetime import UTC, datetime

# 3rd party imports
#
import pytest
import pytest_check as check
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
class TestBudget:
    """Tests for Budget signal-driven complete flag logic."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "budget_type,balance,expected_complete",
        [
            # Only Recurring budgets are completed by the pre_save
            # signal.  Goal completion is driven by funded_amount in the
            # ITX service, and Capped budgets never use the flag, so a
            # non-Recurring budget at its target stays incomplete.
            ("G", 200, False),
            ("R", 200, True),
            ("R", 100, False),
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
        THEN:  complete matches expected_complete (only Recurring at its
               target is complete)
        """
        budget = budget_factory(
            balance=balance, target_balance=200, budget_type=budget_type
        )
        assert budget.complete is expected_complete

    ####################################################################
    #
    def test_fillup_budget_deleted_when_parent_deleted(
        self,
        budget_factory: Callable[..., Budget],
        user: User,
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

        budget_svc.delete(budget, actor=user)

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
    """Tests for InternalTransaction validation and deletion."""

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
        with pytest.raises(ValueError):
            internal_transaction_factory(
                amount=-50,
                src_budget=budget_factory(balance=100),
                dst_budget=budget_factory(balance=100),
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

        src_budget.refresh_from_db()
        dst_budget.refresh_from_db()
        check.equal(src_budget.balance, Money(100, USD), "src restored")
        check.equal(dst_budget.balance, Money(100, USD), "dst restored")


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
    @pytest.fixture
    def funded_account(
        self, bank_account_factory: Callable[..., BankAccount]
    ) -> BankAccount:
        """A bank account with $900 available and $1000 posted."""
        return bank_account_factory(available_balance=900, posted_balance=1000)

    ####################################################################
    #
    @pytest.fixture
    def pending_tx(
        self,
        funded_account: BankAccount,
        transaction_factory: Callable[..., Transaction],
    ) -> Transaction:
        """A pending -$100 transaction on `funded_account`."""
        return transaction_factory(
            amount=-100, pending=True, bank_account=funded_account
        )

    ####################################################################
    #
    def test_pending_then_posted_updates_available_then_posted(
        self, funded_account: BankAccount, pending_tx: Transaction
    ) -> None:
        """
        GIVEN: a bank account with known available and posted balances
        WHEN:  a pending transaction is created against it, and then
               marked as no longer pending (posted)
        THEN:  creating it moves only the available balance; posting it
               then moves the posted balance and leaves available alone
        """
        funded_account.refresh_from_db()
        assert funded_account.available_balance == Money(800, USD)
        assert funded_account.posted_balance == Money(1000, USD)

        transaction_svc.update(pending_tx, pending=False)

        funded_account.refresh_from_db()
        check.equal(funded_account.posted_balance, Money(900, USD), "posted")
        check.equal(
            funded_account.available_balance, Money(800, USD), "available"
        )

    ####################################################################
    #
    def test_amount_change_updates_bank_account_balances(
        self, funded_account: BankAccount, pending_tx: Transaction
    ) -> None:
        """
        GIVEN: a pending transaction with an initial amount (e.g. a petrol
               pre-auth hold that later settles at a different amount)
        WHEN:  the transaction amount is updated and it is marked as posted
        THEN:  the bank account's available and posted balances reflect the
               final settled amount
        """
        transaction_svc.update(
            pending_tx, amount=Money(-28.43, USD), pending=False
        )

        funded_account.refresh_from_db()
        check.equal(
            funded_account.available_balance,
            Money(900 - 28.43, USD),
            "available",
        )
        check.equal(
            funded_account.posted_balance, Money(1000 - 28.43, USD), "posted"
        )

    ####################################################################
    #
    @pytest.mark.parametrize("pending", [True, False])
    def test_delete_restores_bank_account_balances(
        self,
        pending: bool,
        funded_account: BankAccount,
        transaction_factory: Callable[..., Transaction],
    ) -> None:
        """
        GIVEN: a bank account with known balances and a transaction against it,
               with pending=True or pending=False
        WHEN:  the transaction is deleted
        THEN:  both the available and posted balances return to their original
               values regardless of the transaction's pending state
        """
        transaction = transaction_factory(
            amount=-100, pending=pending, bank_account=funded_account
        )
        transaction_svc.delete(transaction)

        funded_account.refresh_from_db()
        check.equal(funded_account.posted_balance, Money(1000, USD), "posted")
        check.equal(
            funded_account.available_balance, Money(900, USD), "available"
        )


########################################################################
########################################################################
#
class TestTransactionAllocation:
    """Tests for TransactionAllocation signal-driven budget balance logic."""

    ####################################################################
    #
    @pytest.fixture
    def budget(
        self, account: BankAccount, budget_factory: Callable[..., Budget]
    ) -> Budget:
        """A budget on `account` holding $500."""
        return budget_factory(bank_account=account, balance=500)

    ####################################################################
    #
    @pytest.fixture
    def allocation(
        self,
        account: BankAccount,
        budget: Budget,
        transaction_factory: Callable[..., Transaction],
        transaction_allocation_factory: Callable[..., TransactionAllocation],
    ) -> TransactionAllocation:
        """A -$100 allocation of a -$100 purchase to `budget`.

        The purchase also keeps the default Unallocated allocation that
        `transaction_svc.create` seeds; only `budget` is under test.
        """
        txn = transaction_factory(amount=-100, bank_account=account)
        return transaction_allocation_factory(
            transaction=txn, budget=budget, amount=-100
        )

    ####################################################################
    #
    def test_create_credits_budget(
        self, budget: Budget, allocation: TransactionAllocation
    ) -> None:
        """
        GIVEN: a transaction and a budget with a known balance
        WHEN:  an allocation is created linking the transaction to the budget
        THEN:  the budget balance changes by the allocation amount and the
               balance snapshot is captured
        """
        budget.refresh_from_db()
        allocation.refresh_from_db()
        check.equal(budget.balance, Money(400, USD), "budget debited")
        check.equal(allocation.budget_balance, budget.balance, "snapshot")

    ####################################################################
    #
    @pytest.mark.parametrize(
        "change,expected_balance",
        [
            pytest.param(transaction_allocation_svc.delete, 500, id="delete"),
            pytest.param(
                lambda alloc: transaction_allocation_svc.update_amount(
                    alloc, Money(-60, USD)
                ),
                440,
                id="update_amount",
            ),
        ],
    )
    def test_change_adjusts_budget_balance(
        self,
        change: Callable[[TransactionAllocation], object],
        expected_balance: int,
        budget: Budget,
        allocation: TransactionAllocation,
    ) -> None:
        """
        GIVEN: a -100 allocation against a budget that held $500
        WHEN:  the allocation is deleted, or its amount changed to -60
        THEN:  the budget balance is adjusted by the difference
        """
        change(allocation)

        budget.refresh_from_db()
        assert budget.balance == Money(expected_balance, USD)

    ####################################################################
    #
    def test_create_defaults_to_unallocated_budget(
        self,
        account: BankAccount,
        transaction_factory: Callable[..., Transaction],
        transaction_allocation_factory: Callable[..., TransactionAllocation],
    ) -> None:
        """
        GIVEN: a transaction against a bank account
        WHEN:  an allocation is created with no budget specified
        THEN:  the allocation is assigned to the bank account's unallocated
               budget
        """
        txn = transaction_factory(amount=-50, bank_account=account)
        alloc = transaction_allocation_factory(
            transaction=txn, budget=None, amount=-50
        )

        assert alloc.budget == account.unallocated_budget

    ####################################################################
    #
    def test_budget_reassignment_moves_balance(
        self,
        bank_account_factory: Callable[..., BankAccount],
        budget_factory: Callable[..., Budget],
        transaction_factory: Callable[..., Transaction],
        internal_transaction_factory: Callable[..., InternalTransaction],
    ) -> None:
        """
        GIVEN: a transaction allocated to the unallocated budget, and a
               destination budget funded to cover the amount
        WHEN:  the allocation's budget is changed to the destination budget
        THEN:  the unallocated budget balance increases (debit removed) and
               the destination budget balance decreases (debit applied)
        """
        bank_account = bank_account_factory(
            available_balance=1000, posted_balance=1000
        )
        unallocated = bank_account.unallocated_budget
        assert unallocated is not None
        dst_budget = budget_factory(balance=0)

        # Fund the destination budget from unallocated
        internal_transaction_factory(
            amount=100, src_budget=unallocated, dst_budget=dst_budget
        )
        assert dst_budget.balance == Money(100, USD)

        txn = transaction_factory(amount=-100, bank_account=bank_account)
        # transaction_factory seeds a default allocation to unallocated.
        alloc = TransactionAllocation.objects.get(transaction=txn)
        assert alloc.budget == unallocated

        # Reassign the allocation to the destination budget via the service
        transaction_allocation_svc.delete(alloc)
        transaction_allocation_svc.create(
            transaction=txn, budget=dst_budget, amount=Money(-100, USD)
        )

        unallocated.refresh_from_db()
        dst_budget.refresh_from_db()
        check.equal(dst_budget.balance, Money(0, USD), "destination debited")
        check.equal(
            unallocated.balance, Money(900, USD), "Unallocated debit removed"
        )

    ####################################################################
    #
    def test_split_transaction_multiple_allocations(
        self,
        account: BankAccount,
        budget_factory: Callable[..., Budget],
        transaction_factory: Callable[..., Transaction],
        transaction_allocation_factory: Callable[..., TransactionAllocation],
    ) -> None:
        """
        GIVEN: a -200 transaction (e.g. a Costco trip with groceries and
               home supplies)
        WHEN:  two allocations are created splitting the amount across two
               budgets
        THEN:  each budget's balance reflects only its portion
        """
        groceries = budget_factory(bank_account=account, balance=300)
        home = budget_factory(bank_account=account, balance=200)
        txn = transaction_factory(
            amount=-200,
            raw_description="COSTCO WHOLESALE",
            bank_account=account,
        )

        transaction_allocation_factory(
            transaction=txn, budget=groceries, amount=-150
        )
        transaction_allocation_factory(transaction=txn, budget=home, amount=-50)

        groceries.refresh_from_db()
        home.refresh_from_db()
        check.equal(groceries.balance, Money(150, USD), "groceries portion")
        check.equal(home.balance, Money(150, USD), "home portion")
        # 3 total: 1 default to unallocated (seeded by transaction_svc.create)
        # + 2 explicit allocations added by this test.
        check.equal(txn.allocations.count(), 3, "three allocations")

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
        account: BankAccount,
        budget: Budget,
        transaction_factory: Callable[..., Transaction],
        transaction_allocation_factory: Callable[..., TransactionAllocation],
        early_date: datetime,
        late_date: datetime,
    ) -> None:
        """
        GIVEN: a budget with $500 and two transactions
        WHEN:  the chronologically later allocation is created first
        THEN:  budget_balance snapshots reflect chronological order,
               not creation order -- first shows $340, second shows
               $180

        When both transactions share a date, chronological order is
        determined by transaction.created_at (creation order).
        """
        # Create earlier_tx first so it gets the earlier created_at.
        # For same-date ties, created_at determines chronological
        # order.
        earlier_tx, later_tx = (
            transaction_factory(
                bank_account=account, amount=-160, posted_date=when
            )
            for when in (early_date, late_date)
        )

        # Allocate the later transaction first (out of order).
        alloc_late = transaction_allocation_factory(
            transaction=later_tx, budget=budget, amount=-160
        )
        alloc_early = transaction_allocation_factory(
            transaction=earlier_tx, budget=budget, amount=-160
        )

        alloc_early.refresh_from_db()
        alloc_late.refresh_from_db()
        # Chronologically first: 500 - 160 = 340
        check.equal(alloc_early.budget_balance, Money(340, USD), "first")
        # Chronologically second: 340 - 160 = 180
        check.equal(alloc_late.budget_balance, Money(180, USD), "second")

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
        a1.refresh_from_db()
        a2.refresh_from_db()
        a3.refresh_from_db()
        check.equal(budget.balance, Money(400, USD), "budget after tx3")
        # The prior two are unchanged.
        check.equal(a1.budget_balance, Money(400, USD), "a1 unchanged")
        check.equal(a2.budget_balance, Money(300, USD), "a2 unchanged")
        # The third reflects the +$200 top-up:
        # 300 + 200 - 100 = 400, not 300 - 100 = 200.
        check.equal(a3.budget_balance, Money(400, USD), "a3 sees the top-up")
