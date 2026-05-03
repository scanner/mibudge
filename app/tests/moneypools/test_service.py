#!/usr/bin/env python
#
"""
Unit tests for the moneypools service layer.

One test class per service, covering the happy path and -- for
TransactionAllocationService -- the concurrency-sensitive case that
demonstrates Redis lock serialization.
"""

# system imports
#
import threading
from collections.abc import Callable
from datetime import UTC, datetime

# 3rd party imports
#
import pytest

# Project imports
#
from common.locks import acquire_lock
from djmoney.money import Money

from moneypools.models import (
    Bank,
    BankAccount,
    Budget,
    Transaction,
)
from moneypools.service import bank_account as bank_account_svc
from moneypools.service import budget as budget_svc
from moneypools.service import internal_transaction as internal_transaction_svc
from moneypools.service import linking as linking_svc
from moneypools.service import transaction as transaction_svc
from moneypools.service import (
    transaction_allocation as transaction_allocation_svc,
)
from users.models import User

pytestmark = pytest.mark.django_db


########################################################################
########################################################################
#
class TestBankAccountService:
    """Tests for service/bank_account.py."""

    ####################################################################
    #
    def test_create_seeds_unallocated_budget_with_initial_balance(
        self,
        bank_factory: Callable[..., Bank],
        user_factory: Callable[..., User],
    ) -> None:
        """
        GIVEN: a bank and an initial available_balance of $500
        WHEN:  BankAccountService.create is called
        THEN:  the account exists, the Unallocated budget is created
               with balance == available_balance, and unallocated_budget_id
               is back-linked on the account row
        """
        user = user_factory()
        bank = bank_factory()
        account = bank_account_svc.create(
            bank=bank,
            name="My Checking",
            account_type=BankAccount.BankAccountType.CHECKING,
            owners=[user],
            available_balance=Money(500, "USD"),
            posted_balance=Money(500, "USD"),
        )

        assert account.pk is not None
        assert account.unallocated_budget is not None
        assert account.unallocated_budget.name == "Unallocated"
        assert account.unallocated_budget.balance == Money(500, "USD")
        assert user in account.owners.all()

        # Verify the back-link is persisted to the DB row, not just the
        # in-memory instance.
        account.refresh_from_db()
        assert account.unallocated_budget_id is not None


########################################################################
########################################################################
#
class TestBudgetService:
    """Tests for service/budget.py."""

    ####################################################################
    #
    def test_create_with_fillup_goal_creates_child(
        self,
        bank_account_factory: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: a RECURRING budget with with_fillup_goal=True
        WHEN:  BudgetService.create is called
        THEN:  an ASSOCIATED_FILLUP_GOAL child is created and linked
               back via fillup_goal
        """
        account = bank_account_factory()
        budget = budget_svc.create(
            bank_account=account,
            name="Groceries",
            budget_type=Budget.BudgetType.RECURRING,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(200, "USD"),
            with_fillup_goal=True,
        )

        assert budget.fillup_goal is not None
        assert (
            budget.fillup_goal.budget_type
            == Budget.BudgetType.ASSOCIATED_FILLUP_GOAL
        )
        assert budget.fillup_goal.name == "Groceries Fill-up"
        assert budget.fillup_goal.target_balance == Money(200, "USD")

    ####################################################################
    #
    @pytest.mark.parametrize(
        "field,new_value,fillup_attr,expected",
        [
            (
                "target_balance",
                Money(300, "USD"),
                "target_balance",
                Money(300, "USD"),
            ),
            (
                "name",
                "Rent",
                "name",
                "Rent Fill-up",
            ),
        ],
    )
    def test_update_syncs_fillup_goal(
        self,
        field: str,
        new_value: object,
        fillup_attr: str,
        expected: object,
        bank_account_factory: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: a RECURRING budget with an existing fill-up goal
        WHEN:  budget_svc.update() changes target_balance or name
        THEN:  the fill-up goal's corresponding field is updated to match
        """
        account = bank_account_factory()
        budget = budget_svc.create(
            bank_account=account,
            name="Groceries",
            budget_type=Budget.BudgetType.RECURRING,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(200, "USD"),
            with_fillup_goal=True,
        )
        assert budget.fillup_goal is not None

        budget_svc.update(budget, **{field: new_value})

        budget.fillup_goal.refresh_from_db()
        assert getattr(budget.fillup_goal, fillup_attr) == expected

    ####################################################################
    #
    def test_update_unrelated_field_does_not_touch_fillup_goal(
        self,
        bank_account_factory: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: a RECURRING budget with an existing fill-up goal
        WHEN:  budget_svc.update() changes a field not in _FILLUP_SYNCED_FIELDS
        THEN:  the fill-up goal is not modified
        """
        account = bank_account_factory()
        budget = budget_svc.create(
            bank_account=account,
            name="Groceries",
            budget_type=Budget.BudgetType.RECURRING,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(200, "USD"),
            with_fillup_goal=True,
        )
        assert budget.fillup_goal is not None
        fillup_before = budget.fillup_goal.modified_at

        budget_svc.update(budget, memo="updated memo")

        budget.fillup_goal.refresh_from_db()
        assert budget.fillup_goal.modified_at == fillup_before


########################################################################
########################################################################
#
class TestInternalTransactionService:
    """Tests for service/internal_transaction.py."""

    ####################################################################
    #
    def test_create_adjusts_budget_balances(
        self,
        bank_account_factory: Callable[..., BankAccount],
        budget_factory: Callable[..., Budget],
        user_factory: Callable[..., User],
    ) -> None:
        """
        GIVEN: two budgets with known balances
        WHEN:  InternalTransactionService.create transfers $50 src -> dst
        THEN:  src decreases by $50, dst increases by $50, and the
               snapshot fields on the row reflect post-transfer balances
        """
        account = bank_account_factory(available_balance=Money(200, "USD"))
        src = account.unallocated_budget
        assert src is not None
        dst = budget_factory(
            bank_account=account,
            balance=Money(0, "USD"),
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
        )
        actor = user_factory()
        initial_src = src.balance

        it = internal_transaction_svc.create(
            bank_account=account,
            src_budget=src,
            dst_budget=dst,
            amount=Money(50, "USD"),
            actor=actor,
        )

        src.refresh_from_db()
        dst.refresh_from_db()
        assert src.balance == initial_src - Money(50, "USD")
        assert dst.balance == Money(50, "USD")
        assert it.src_budget_balance == src.balance
        assert it.dst_budget_balance == dst.balance

    ####################################################################
    #
    def test_historical_itx_updates_later_snapshots(
        self,
        bank_account_factory: Callable[..., BankAccount],
        budget_factory: Callable[..., Budget],
        user_factory: Callable[..., User],
    ) -> None:
        """
        GIVEN: two forward ITxs (A at day1, B at day30) from Unallocated
        WHEN:  a third historical ITx (C at day1, created after A) is inserted
        THEN:  C's src_budget_balance snapshot is corrected to reflect the
               balance after A but before C, and B's src_budget_balance is
               recalculated to account for the extra debit from C
        """
        day1 = datetime(2024, 1, 1, tzinfo=UTC)
        day30 = datetime(2024, 1, 30, tzinfo=UTC)

        account = bank_account_factory(available_balance=Money(1200, "USD"))
        unallocated = account.unallocated_budget
        assert unallocated is not None
        eat = budget_factory(
            bank_account=account,
            balance=Money(0, "USD"),
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
        )
        spend = budget_factory(
            bank_account=account,
            balance=Money(0, "USD"),
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
        )
        actor = user_factory()

        # ITx A: day1, Unallocated -> Eat, $400
        itx_a = internal_transaction_svc.create(
            bank_account=account,
            src_budget=unallocated,
            dst_budget=eat,
            amount=Money(400, "USD"),
            actor=actor,
            effective_date=day1,
        )
        assert itx_a.src_budget_balance == Money(800, "USD")

        # ITx B: day30, Unallocated -> Eat, $400
        itx_b = internal_transaction_svc.create(
            bank_account=account,
            src_budget=unallocated,
            dst_budget=eat,
            amount=Money(400, "USD"),
            actor=actor,
            effective_date=day30,
        )
        assert itx_b.src_budget_balance == Money(400, "USD")

        # ITx C: historical, day1 (created after A), Unallocated -> Spend, $200
        itx_c = internal_transaction_svc.create(
            bank_account=account,
            src_budget=unallocated,
            dst_budget=spend,
            amount=Money(200, "USD"),
            actor=actor,
            effective_date=day1,
        )

        # C's snapshot: Unallocated was $1200 before A, $800 after A, $600 after C
        itx_c.refresh_from_db()
        assert itx_c.src_budget_balance == Money(600, "USD")

        # B's snapshot must be updated: $1200 - $400 (A) - $200 (C) = $600 before B
        itx_b.refresh_from_db()
        assert itx_b.src_budget_balance == Money(200, "USD")


########################################################################
########################################################################
#
class TestTransactionAllocationService:
    """Tests for service/transaction_allocation.py."""

    ####################################################################
    #
    def test_create_credits_budget_balance(
        self,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
        budget_factory: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: a transaction and a target budget
        WHEN:  TransactionAllocationService.create allocates the full amount
        THEN:  the budget's balance increases by that amount and the
               allocation row is saved with the correct budget_balance snapshot
        """
        account = bank_account_factory(available_balance=Money(100, "USD"))
        tx = transaction_factory(bank_account=account, amount=Money(100, "USD"))
        dst = budget_factory(
            bank_account=account,
            balance=Money(0, "USD"),
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
        )
        before = dst.balance

        alloc = transaction_allocation_svc.create(
            transaction=tx,
            budget=dst,
            amount=Money(50, "USD"),
        )

        dst.refresh_from_db()
        alloc.refresh_from_db()
        assert dst.balance == before + Money(50, "USD")
        assert alloc.budget_balance == dst.balance

    ####################################################################
    #
    def test_budget_lock_gates_concurrent_callers(
        self,
        bank_account_factory: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: the Redis lock for a budget key is already held
        WHEN:  a second caller tries to acquire the same lock
        THEN:  it blocks until the first caller releases, then succeeds

        This verifies that the Redis lock correctly serializes concurrent
        accesses to the same budget, which is the mechanism all
        TransactionAllocationService operations rely on to prevent
        lost-update races on budget.balance.
        """
        account = bank_account_factory()
        budget = account.unallocated_budget
        assert budget is not None
        key = budget.lock_key

        second_started = threading.Event()
        second_acquired = threading.Event()

        def second_caller() -> None:
            second_started.set()
            with acquire_lock(key):
                second_acquired.set()

        with acquire_lock(key):
            t = threading.Thread(target=second_caller, daemon=True)
            t.start()
            second_started.wait(timeout=1.0)
            # Second caller is blocked -- lock is still held by this thread.
            assert not second_acquired.wait(timeout=0.15), (
                "second caller should block while lock is held"
            )

        # Lock released; second caller should now complete promptly.
        assert second_acquired.wait(timeout=2.0), (
            "second caller should acquire lock after first releases"
        )
        t.join(timeout=2.0)


########################################################################
########################################################################
#
class TestTransactionService:
    """Tests for service/transaction.py."""

    ####################################################################
    #
    def test_create_applies_bank_balance_and_seeds_allocation(
        self,
        bank_account_factory: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: a bank account with $0 balance
        WHEN:  TransactionService.create saves a $200 deposit
        THEN:  available_balance and posted_balance each increase by $200,
               and one TransactionAllocation pointing at Unallocated is created
        """
        account = bank_account_factory(
            available_balance=Money(0, "USD"),
            posted_balance=Money(0, "USD"),
        )
        tx = transaction_svc.create(
            bank_account=account,
            amount=Money(200, "USD"),
            posted_date=datetime.now(UTC),
            raw_description="DIRECT DEPOSIT",
        )

        account.refresh_from_db()
        assert account.available_balance == Money(200, "USD")
        assert account.posted_balance == Money(200, "USD")

        allocs = list(tx.allocations.all())
        assert len(allocs) == 1
        assert allocs[0].budget == account.unallocated_budget
        assert allocs[0].amount == Money(200, "USD")


########################################################################
########################################################################
#
class TestLinkingService:
    """Tests for service/linking.py."""

    ####################################################################
    #
    def test_attempt_link_pairs_matching_transactions(
        self,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
        user_factory: Callable[..., User],
    ) -> None:
        """
        GIVEN: two co-owned accounts with counterpart transactions
        WHEN:  attempt_link runs on the driving transaction
        THEN:  both rows are linked to each other
        """
        user = user_factory()
        src = bank_account_factory(
            name="BofA Checking",
            account_number="000011112222",
            owners=[user],
        )
        dst = bank_account_factory(
            name="AppleCard",
            account_number="333344445678",
            owners=[user],
        )

        when = datetime(2026, 3, 10, 12, tzinfo=UTC)
        counterpart = transaction_factory(
            bank_account=dst,
            amount=Money(100, "USD"),
            posted_date=when,
            raw_description="counterpart",
        )
        driving = transaction_factory(
            bank_account=src,
            amount=Money(-100, "USD"),
            posted_date=when,
            raw_description="ACH Transfer to APPLECARD",
        )

        result = linking_svc.attempt_link(driving)

        assert result is not None
        assert result.pkid == counterpart.pkid
        driving.refresh_from_db()
        counterpart.refresh_from_db()
        assert driving.linked_transaction_id == counterpart.id
        assert counterpart.linked_transaction_id == driving.id
