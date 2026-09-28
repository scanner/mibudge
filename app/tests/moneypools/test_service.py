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
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

# 3rd party imports
#
import pytest
import pytest_check as check
import recurrence
from djmoney.money import Money
from freezegun import freeze_time

# Project imports
#
from common.locks import acquire_lock
from moneypools.management.commands.verify_balances import (
    _check_budget_chain,
)
from moneypools.models import (
    Bank,
    BankAccount,
    Budget,
    Transaction,
    TransactionAllocation,
)
from moneypools.service import bank_account as bank_account_svc
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
class TestBankAccountService:
    """Tests for service/bank_account.py."""

    ####################################################################
    #
    def test_create_seeds_unallocated_budget_with_initial_balance(
        self,
        bank_factory: Callable[..., Bank],
        user: User,
    ) -> None:
        """
        GIVEN: a bank and an initial available_balance of $500
        WHEN:  BankAccountService.create is called
        THEN:  the account exists, the Unallocated budget is created
               with balance == available_balance and belongs to the
               account, and unallocated_budget_id is back-linked on the
               account row
        """
        account = bank_account_svc.create(
            bank=bank_factory(),
            name="My Checking",
            account_type=BankAccount.BankAccountType.CHECKING,
            owners=[user],
            available_balance=Money(500, "USD"),
            posted_balance=Money(500, "USD"),
        )

        assert account.pk is not None
        unallocated = account.unallocated_budget
        assert unallocated is not None
        check.equal(unallocated.name, "Unallocated", "named Unallocated")
        check.equal(unallocated.balance, Money(500, "USD"), "seeded balance")
        check.equal(unallocated.bank_account, account, "on the account")
        check.is_in(user, list(account.owners.all()), "owned by the user")

        # The back-link is persisted to the DB row, not just the
        # in-memory instance.
        account.refresh_from_db()
        check.is_not_none(account.unallocated_budget_id, "back-link saved")


########################################################################
########################################################################
#
class TestBudgetService:
    """Tests for service/budget.py."""

    ####################################################################
    #
    @pytest.fixture
    def recurring_budget(
        self,
        account: BankAccount,
        make_budget: Callable[..., Budget],
    ) -> Budget:
        """A $200 Recurring budget named 'Groceries', with its fill-up."""
        return make_budget(
            account,
            name="Groceries",
            budget_type=Budget.BudgetType.RECURRING,
            funding_type=Budget.FundingType.TARGET_DATE,
            target_balance=Money(200, "USD"),
        )

    ####################################################################
    #
    def test_create_recurring_creates_fillup_child(
        self, account: BankAccount
    ) -> None:
        """
        GIVEN: a RECURRING budget
        WHEN:  BudgetService.create is called
        THEN:  the returned budget carries an ASSOCIATED_FILLUP_GOAL
               child on the same account, linked back via fillup_goal
        """
        budget = budget_svc.create(
            bank_account=account,
            name="Groceries",
            budget_type=Budget.BudgetType.RECURRING,
            funding_type=Budget.FundingType.TARGET_DATE,
            target_balance=Money(200, "USD"),
        )

        fillup = budget.fillup_goal
        assert fillup is not None
        check.equal(
            fillup.budget_type,
            Budget.BudgetType.ASSOCIATED_FILLUP_GOAL,
            "fill-up type",
        )
        check.equal(fillup.name, "Groceries Fill-up", "named for its parent")
        check.equal(fillup.target_balance, Money(200, "USD"), "same target")
        check.equal(fillup.bank_account, account, "same account")

    ####################################################################
    #
    @pytest.mark.parametrize(
        "field,new_value,expected",
        [
            ("target_balance", Money(300, "USD"), Money(300, "USD")),
            ("name", "Rent", "Rent Fill-up"),
        ],
    )
    def test_update_syncs_fillup_goal(
        self,
        field: str,
        new_value: object,
        expected: object,
        recurring_budget: Budget,
    ) -> None:
        """
        GIVEN: a RECURRING budget with an existing fill-up goal
        WHEN:  budget_svc.update() changes target_balance or name
        THEN:  the fill-up goal's corresponding field is updated to match
        """
        fillup = recurring_budget.fillup_goal
        assert fillup is not None

        budget_svc.update(recurring_budget, **{field: new_value})

        fillup.refresh_from_db()
        assert getattr(fillup, field) == expected

    ####################################################################
    #
    def test_update_unrelated_field_does_not_touch_fillup_goal(
        self, recurring_budget: Budget
    ) -> None:
        """
        GIVEN: a RECURRING budget with an existing fill-up goal
        WHEN:  budget_svc.update() changes a field not in _FILLUP_SYNCED_FIELDS
        THEN:  the fill-up goal is not modified
        """
        fillup = recurring_budget.fillup_goal
        assert fillup is not None
        fillup_before = fillup.modified_at

        budget_svc.update(recurring_budget, memo="updated memo")

        fillup.refresh_from_db()
        assert fillup.modified_at == fillup_before

    ####################################################################
    #
    @pytest.mark.parametrize(
        "dtstart,expected",
        [
            # Bare schedule (the SPA shape): anchored at the first real
            # rule occurrence on/after today (frozen to 2026-06-01).
            (None, datetime(2026, 6, 15)),
            # Explicit DTSTART (e.g. an account import): trusted as-is.
            # Supplied UTC-aware, the storage convention; a naive value
            # would be reinterpreted as local time on serialization.
            (datetime(2026, 1, 15, tzinfo=UTC), datetime(2026, 1, 15)),
        ],
    )
    @freeze_time("2026-06-01")
    def test_create_anchors_funding_schedule_dtstart(
        self,
        dtstart: datetime | None,
        expected: datetime,
        account: BankAccount,
    ) -> None:
        """
        GIVEN: a new budget whose funding schedule arrives bare or with
               an explicit DTSTART
        WHEN:  the budget is created
        THEN:  a bare schedule is anchored on its first real occurrence
               from today; an explicit DTSTART is preserved
        """
        budget = budget_svc.create(
            bank_account=account,
            name="Trip",
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.TARGET_DATE,
            target_balance=Money(1000, "USD"),
            target_date=date(2026, 12, 1),
            funding_schedule=recurrence.Recurrence(
                dtstart=dtstart,
                rrules=[
                    recurrence.Rule(recurrence.MONTHLY, bymonthday=[15, -1])
                ],
            ),
        )

        budget.refresh_from_db()
        assert budget.funding_schedule.dtstart is not None
        assert budget.funding_schedule.dtstart.replace(tzinfo=None) == expected

    ####################################################################
    #
    @pytest.mark.parametrize(
        "new_bymonthday,other_changes,expected_dtstart",
        [
            # Funding dates changed (new pattern, sent bare as the SPA
            # does): re-anchor on the new rule's first occurrence from
            # the edit date (frozen to 2026-07-20).
            ([1], {}, datetime(2026, 8, 1)),
            # Goal date changed, same pattern echoed bare: re-anchor
            # forward from the edit date, keeping the stored anchor as
            # the rule anchor.
            (
                [15, -1],
                {"target_date": date(2027, 1, 1)},
                datetime(2026, 7, 31),
            ),
            # Nothing schedule-relevant changed; the client just echoed
            # the pattern without its anchor: stored DTSTART preserved.
            ([15, -1], {}, datetime(2026, 6, 15)),
        ],
    )
    def test_update_reanchors_funding_schedule(
        self,
        new_bymonthday: list[int],
        other_changes: dict[str, Any],
        expected_dtstart: datetime,
        account: BankAccount,
    ) -> None:
        """
        GIVEN: a Goal budget created 2026-06-01 with a semi-monthly
               schedule anchored at Jun 15, target date Dec 1
        WHEN:  budget_svc.update runs on 2026-07-20 with a changed
               funding pattern, a changed goal date, or a mere bare echo
               of the stored schedule
        THEN:  pattern/date changes re-figure the schedule (DTSTART moves
               to the first real occurrence from the edit date) while a
               bare echo keeps the stored anchor
        """
        with freeze_time("2026-06-01"):
            budget = budget_svc.create(
                bank_account=account,
                name="Trip",
                budget_type=Budget.BudgetType.GOAL,
                funding_type=Budget.FundingType.TARGET_DATE,
                target_balance=Money(1000, "USD"),
                target_date=date(2026, 12, 1),
                funding_schedule=recurrence.Recurrence(
                    rrules=[
                        recurrence.Rule(recurrence.MONTHLY, bymonthday=[15, -1])
                    ],
                ),
            )

        # SPA full-object updates always send the schedule bare.
        schedule = recurrence.Recurrence(
            rrules=[
                recurrence.Rule(recurrence.MONTHLY, bymonthday=new_bymonthday)
            ],
        )
        with freeze_time("2026-07-20"):
            budget_svc.update(
                budget, funding_schedule=schedule, **other_changes
            )

        budget.refresh_from_db()
        dtstart = budget.funding_schedule.dtstart
        assert dtstart is not None
        assert dtstart.replace(tzinfo=None) == expected_dtstart


########################################################################
########################################################################
#
class TestInternalTransactionService:
    """Tests for service/internal_transaction.py."""

    ####################################################################
    #
    def test_create_adjusts_budget_balances(
        self,
        account: BankAccount,
        unallocated: Budget,
        goal: Budget,
        user: User,
    ) -> None:
        """
        GIVEN: $200 in Unallocated and an empty Goal
        WHEN:  InternalTransactionService.create transfers $50 src -> dst
        THEN:  src decreases by $50, dst increases by $50, and the
               snapshot fields on the row reflect post-transfer balances
        """
        Budget.objects.filter(pkid=unallocated.pkid).update(
            balance=Money(200, "USD")
        )
        unallocated.refresh_from_db()

        it = internal_transaction_svc.create(
            bank_account=account,
            src_budget=unallocated,
            dst_budget=goal,
            amount=Money(50, "USD"),
            actor=user,
        )

        unallocated.refresh_from_db()
        goal.refresh_from_db()
        check.equal(unallocated.balance, Money(150, "USD"), "src debited")
        check.equal(goal.balance, Money(50, "USD"), "dst credited")
        check.equal(it.src_budget_balance, unallocated.balance, "src snapshot")
        check.equal(it.dst_budget_balance, goal.balance, "dst snapshot")

    ####################################################################
    #
    def test_historical_itx_updates_later_snapshots(
        self,
        bank_account_factory: Callable[..., BankAccount],
        budget_factory: Callable[..., Budget],
        user: User,
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
        eat, spend = (
            budget_factory(
                bank_account=account,
                balance=Money(0, "USD"),
                budget_type=Budget.BudgetType.GOAL,
                funding_type=Budget.FundingType.FIXED_AMOUNT,
            )
            for _ in range(2)
        )

        # ITx A: day1, Unallocated -> Eat, $400
        itx_a = internal_transaction_svc.create(
            bank_account=account,
            src_budget=unallocated,
            dst_budget=eat,
            amount=Money(400, "USD"),
            actor=user,
            effective_date=day1,
        )
        assert itx_a.src_budget_balance == Money(800, "USD")

        # ITx B: day30, Unallocated -> Eat, $400
        itx_b = internal_transaction_svc.create(
            bank_account=account,
            src_budget=unallocated,
            dst_budget=eat,
            amount=Money(400, "USD"),
            actor=user,
            effective_date=day30,
        )
        assert itx_b.src_budget_balance == Money(400, "USD")

        # ITx C: historical, day1 (created after A), Unallocated -> Spend, $200
        itx_c = internal_transaction_svc.create(
            bank_account=account,
            src_budget=unallocated,
            dst_budget=spend,
            amount=Money(200, "USD"),
            actor=user,
            effective_date=day1,
        )

        # C's snapshot: Unallocated was $1200 before A, $800 after A, $600 after C
        itx_c.refresh_from_db()
        check.equal(itx_c.src_budget_balance, Money(600, "USD"), "C snapshot")

        # B's snapshot must be updated: $1200 - $400 (A) - $200 (C) = $600 before B
        itx_b.refresh_from_db()
        check.equal(itx_b.src_budget_balance, Money(200, "USD"), "B updated")


########################################################################
########################################################################
#
class TestTransactionAllocationService:
    """Tests for service/transaction_allocation.py."""

    ####################################################################
    #
    def test_budget_lock_gates_concurrent_callers(
        self, unallocated: Budget
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
        key = unallocated.lock_key

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

    ####################################################################
    #
    def test_running_balances_updated_across_interleaved_allocations_and_itxs(
        self,
        bank_account_factory: Callable[..., BankAccount],
        budget_factory: Callable[..., Budget],
        user: User,
    ) -> None:
        """
        GIVEN: three transactions at dt1, dt2, dt4 exist in the system
        WHEN:  (1) tx_dt2 and tx_dt4 are allocated to Groceries
               (2) a funding ITx from Unallocated -> Groceries is inserted
                   at effective_date dt3 (between the two allocations)
               (3) tx_dt1 is allocated to Groceries (the "forgotten" alloc)
        THEN:  all budget_balance snapshots on Groceries allocations and
               src/dst_budget_balance snapshots on the ITx are consistent
               with the chronological order of each budget's event stream
               (transaction_date for allocs, effective_date for ITxs)

        Event timeline (chronological):
          dt1   tx_dt1  $+100   allocated in phase 3 (after the ITx)
          dt2   tx_dt2  $-100   allocated in phase 1
          dt3   ITx     $+100   Unallocated -> Groceries, inserted in phase 2
          dt4   tx_dt4  $-200   allocated in phase 1

        Groceries seed balance: $400
        Unallocated seed balance: $500 (via bank account posted_balance)
        """
        dt1 = datetime(2024, 1, 1, tzinfo=UTC)
        dt2 = datetime(2024, 2, 1, tzinfo=UTC)
        dt3 = datetime(2024, 3, 1, tzinfo=UTC)
        dt4 = datetime(2024, 4, 1, tzinfo=UTC)

        account = bank_account_factory(
            posted_balance=Money(500, "USD"),
            available_balance=Money(500, "USD"),
        )
        unallocated = account.unallocated_budget
        assert unallocated is not None

        # Groceries is seeded at $400; the test verifies snapshot consistency,
        # not the account-level sum(budget.balance)==posted_balance invariant.
        #
        groceries = budget_factory(
            bank_account=account,
            balance=Money(400, "USD"),
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
        )

        # Create all transactions upfront in chronological order.  Transactions
        # are not created out of order; it is the allocation of those
        # transactions to budgets that is staged across the three phases.
        # Transaction.objects.create is used directly to skip the bank-account
        # balance update in transaction_svc.create, which is not under test.
        #
        tx_dt1, tx_dt2, tx_dt4 = (
            Transaction.objects.create(
                bank_account=account,
                amount=Money(amount, "USD"),  # type: ignore[misc]
                posted_date=when,
                transaction_date=when,
                raw_description=f"Grocery {when.date()}",
                transaction_type=Transaction.TransactionType.SIGNATURE_PURCHASE,
            )
            for amount, when in ((100, dt1), (-100, dt2), (-200, dt4))
        )

        # -- phase 1: allocate dt2 and dt4 transactions to Groceries ----
        #
        alloc_dt2 = transaction_allocation_svc.create(
            transaction=tx_dt2, budget=groceries, amount=Money(-100, "USD")
        )
        alloc_dt4 = transaction_allocation_svc.create(
            transaction=tx_dt4, budget=groceries, amount=Money(-200, "USD")
        )

        # Groceries: $400 seed -> $300 (dt2) -> $100 (dt4)
        #
        alloc_dt2.refresh_from_db()
        alloc_dt4.refresh_from_db()
        assert alloc_dt2.budget_balance == Money(300, "USD")
        assert alloc_dt4.budget_balance == Money(100, "USD")

        # -- phase 2: backdated ITx at dt3, Unallocated -> Groceries ----
        #
        itx = internal_transaction_svc.create(
            bank_account=account,
            src_budget=unallocated,
            dst_budget=groceries,
            amount=Money(100, "USD"),
            actor=user,
            effective_date=dt3,
        )

        # Groceries chain after ITx:
        #   alloc_dt2:     $400 seed -> $300           (unchanged; ITx is after dt2)
        #   itx.dst:       running $300 + $100 = $400  (credit at dt3)
        #   alloc_dt4:     running $400 - $200 = $200  (debit at dt4)
        # Unallocated chain:
        #   itx.src:       $500 seed - $100 = $400     (debit at dt3)
        #
        itx.refresh_from_db()
        alloc_dt2.refresh_from_db()
        alloc_dt4.refresh_from_db()
        assert alloc_dt2.budget_balance == Money(300, "USD")
        assert itx.dst_budget_balance == Money(400, "USD")
        assert alloc_dt4.budget_balance == Money(200, "USD")
        assert itx.src_budget_balance == Money(400, "USD")

        # -- phase 3: allocate the dt1 transaction to Groceries ---------
        #
        alloc_dt1 = transaction_allocation_svc.create(
            transaction=tx_dt1, budget=groceries, amount=Money(100, "USD")
        )

        # Adding $100 at dt1 shifts every later Groceries snapshot by +$100.
        # Unallocated has no allocations so its ITx snapshot is unchanged.
        #
        # Groceries chain after dt1 alloc:
        #   alloc_dt1:   $400 seed + $100 = $500
        #   alloc_dt2:   running $500 - $100 = $400
        #   itx.dst:     running $400 + $100 = $500
        #   alloc_dt4:   running $500 - $200 = $300
        # Unallocated chain (unchanged):
        #   itx.src:     $400
        #
        alloc_dt1.refresh_from_db()
        alloc_dt2.refresh_from_db()
        itx.refresh_from_db()
        alloc_dt4.refresh_from_db()
        check.equal(alloc_dt1.budget_balance, Money(500, "USD"), "dt1 alloc")
        check.equal(alloc_dt2.budget_balance, Money(400, "USD"), "dt2 alloc")
        check.equal(itx.dst_budget_balance, Money(500, "USD"), "ITx dst")
        check.equal(alloc_dt4.budget_balance, Money(300, "USD"), "dt4 alloc")
        check.equal(itx.src_budget_balance, Money(400, "USD"), "ITx src")


########################################################################
########################################################################
#
class TestTransactionService:
    """Tests for service/transaction.py."""

    ####################################################################
    #
    @pytest.fixture
    def funded_account(
        self, bank_account_factory: Callable[..., BankAccount]
    ) -> BankAccount:
        """A bank account with $1000 available and posted."""
        return bank_account_factory(
            available_balance=Money(1000, "USD"),
            posted_balance=Money(1000, "USD"),
        )

    ####################################################################
    #
    @pytest.fixture
    def make_pending(
        self, funded_account: BankAccount
    ) -> Callable[..., Transaction]:
        """Return a factory for pending purchases on `funded_account`.

        Returns:
            A callable `(amount=-50) -> Transaction`, dated 2026-05-01.
        """

        def _make(amount: int = -50) -> Transaction:
            return transaction_svc.create(
                bank_account=funded_account,
                amount=Money(amount, "USD"),
                posted_date=datetime(2026, 5, 1, tzinfo=UTC),
                raw_description="PENDING PURCHASE",
                pending=True,
            )

        return _make

    ####################################################################
    #
    def test_create_applies_bank_balance_and_seeds_allocation(
        self, account: BankAccount
    ) -> None:
        """
        GIVEN: a bank account with $0 balance
        WHEN:  TransactionService.create saves a $200 deposit
        THEN:  available_balance and posted_balance each increase by $200,
               and one TransactionAllocation pointing at Unallocated is created
        """
        tx = transaction_svc.create(
            bank_account=account,
            amount=Money(200, "USD"),
            posted_date=datetime.now(UTC),
            raw_description="DIRECT DEPOSIT",
        )

        account.refresh_from_db()
        check.equal(account.available_balance, Money(200, "USD"), "available")
        check.equal(account.posted_balance, Money(200, "USD"), "posted")
        check.equal(
            [(a.budget, a.amount) for a in tx.allocations.all()],
            [(account.unallocated_budget, Money(200, "USD"))],
            "one allocation to Unallocated",
        )

    ####################################################################
    #
    def test_split_raises_for_pending_transaction(
        self, make_pending: Callable[..., Transaction]
    ) -> None:
        """
        GIVEN: a pending transaction
        WHEN:  transaction_svc.split() is called on it
        THEN:  ValueError is raised with a clear message
        """
        with pytest.raises(ValueError, match="Cannot split a pending"):
            transaction_svc.split(make_pending(), {})

    ####################################################################
    #
    @pytest.mark.parametrize(
        "pending_amount, new_amount, expected_avail_delta, expected_final",
        [
            # Same amount: available_balance unchanged, just clears pending flag.
            (-75, None, Money(0, "USD"), Money(-75, "USD")),
            # Amount changed: available_balance adjusted by the delta (-100 -> -90).
            (-100, Money(-90, "USD"), Money(10, "USD"), Money(-90, "USD")),
        ],
        ids=["same_amount", "amount_changed"],
    )
    def test_resolve_pending_to_posted(
        self,
        funded_account: BankAccount,
        make_pending: Callable[..., Transaction],
        pending_amount: int,
        new_amount: Money | None,
        expected_avail_delta: Money,
        expected_final: Money,
    ) -> None:
        """
        GIVEN: a pending debit transaction
        WHEN:  resolve_pending_to_posted is called (optionally with a new amount)
        THEN:  pending is cleared, posted_balance is credited by the final amount,
               available_balance is adjusted by the delta (zero when unchanged),
               and the Unallocated allocation reflects the final amount
        """
        tx = make_pending(pending_amount)
        funded_account.refresh_from_db()
        unalloc = funded_account.unallocated_budget
        assert unalloc is not None

        avail_before = funded_account.available_balance
        posted_before = funded_account.posted_balance

        resolved = transaction_svc.resolve_pending_to_posted(
            tx,
            new_posted_date=datetime(2026, 5, 3, tzinfo=UTC),
            new_amount=new_amount,
        )

        funded_account.refresh_from_db()
        unalloc.refresh_from_db()

        check.is_false(resolved.pending, "no longer pending")
        check.equal(resolved.amount, expected_final, "final amount")
        check.equal(
            funded_account.available_balance,
            avail_before + expected_avail_delta,
            "available adjusted by the delta",
        )
        check.equal(
            funded_account.posted_balance,
            posted_before + expected_final,
            "posted by the final amount",
        )
        check.equal(
            [
                a.amount
                for a in TransactionAllocation.objects.filter(
                    transaction=resolved
                )
            ],
            [expected_final],
            "one allocation of the final amount",
        )
        # Unallocated was seeded with account.available_balance (1000),
        # so its balance after resolution = seed + final allocation.
        check.equal(
            unalloc.balance,
            Money(1000, "USD") + expected_final,
            "Unallocated follows",
        )

    ####################################################################
    #
    def test_resolve_pending_raises_if_already_posted(
        self, account: BankAccount
    ) -> None:
        """
        GIVEN: a posted (non-pending) transaction
        WHEN:  resolve_pending_to_posted is called
        THEN:  ValueError is raised
        """
        tx = transaction_svc.create(
            bank_account=account,
            amount=Money(-50, "USD"),
            posted_date=datetime.now(UTC),
            raw_description="POSTED TX",
        )
        with pytest.raises(ValueError, match="not pending"):
            transaction_svc.resolve_pending_to_posted(
                tx, new_posted_date=datetime.now(UTC)
            )

    ####################################################################
    #
    def test_resolve_pending_twice_credits_posted_balance_once(
        self,
        funded_account: BankAccount,
        make_pending: Callable[..., Transaction],
    ) -> None:
        """
        GIVEN: a pending -$50 transaction, loaded by two callers
        WHEN:  both callers resolve it to posted, one after the other
        THEN:  posted_balance drops by $50 exactly once
        AND:   the second resolve raises ValueError
        """
        tx = make_pending()
        # Both copies are loaded while the row is still pending, as two
        # concurrent requests would load it.
        #
        first_copy = Transaction.objects.get(pk=tx.pk)
        second_copy = Transaction.objects.get(pk=tx.pk)
        posted_date = datetime(2026, 5, 3, tzinfo=UTC)

        transaction_svc.resolve_pending_to_posted(
            first_copy, new_posted_date=posted_date
        )
        with pytest.raises(ValueError, match="not pending"):
            transaction_svc.resolve_pending_to_posted(
                second_copy, new_posted_date=posted_date
            )

        funded_account.refresh_from_db()
        assert funded_account.posted_balance == Money(950, "USD")

    ####################################################################
    #
    def test_update_to_posted_twice_credits_posted_balance_once(
        self,
        funded_account: BankAccount,
        make_pending: Callable[..., Transaction],
    ) -> None:
        """
        GIVEN: a pending -$50 transaction, loaded by two callers
        WHEN:  both callers update it to `pending=False`
        THEN:  posted_balance drops by $50 exactly once
        """
        tx = make_pending()
        first_copy = Transaction.objects.get(pk=tx.pk)
        second_copy = Transaction.objects.get(pk=tx.pk)

        transaction_svc.update(first_copy, pending=False)
        transaction_svc.update(second_copy, pending=False)

        funded_account.refresh_from_db()
        assert funded_account.posted_balance == Money(950, "USD")

    ####################################################################
    #
    def test_resolve_with_new_date_keeps_unallocated_chain_valid(
        self,
        funded_account: BankAccount,
        make_pending: Callable[..., Transaction],
    ) -> None:
        """
        GIVEN: a pending -$10 transaction dated May 1 and a posted -$5
               transaction dated May 5, both in Unallocated
        WHEN:  the pending transaction resolves with the same amount
               and a May 10 posted date, moving it after the May 5 one
        THEN:  Unallocated's running-balance chain is valid
        """
        pending_tx = make_pending(-10)
        transaction_svc.create(
            bank_account=funded_account,
            amount=Money(-5, "USD"),
            posted_date=datetime(2026, 5, 5, tzinfo=UTC),
            raw_description="POSTED PURCHASE",
        )

        transaction_svc.resolve_pending_to_posted(
            pending_tx, new_posted_date=datetime(2026, 5, 10, tzinfo=UTC)
        )

        unallocated = funded_account.unallocated_budget
        assert unallocated is not None
        unallocated.refresh_from_db()
        assert _check_budget_chain(unallocated, Decimal("0")) == []
