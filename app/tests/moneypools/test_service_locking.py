#!/usr/bin/env python
#
"""
Tests that the service layer re-reads balance rows under a row lock.

SQLite ignores `SELECT ... FOR UPDATE`, so these tests record the calls
to `moneypools.service._locking.locked` rather than observing blocking.
The threaded tests in `test_concurrency_postgres.py` exercise the real
row locks against Postgres.
"""

# system imports
#
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal

# 3rd party imports
#
import pytest
import recurrence
from django.db import models
from djmoney.money import Money
from pytest_mock import MockerFixture

# Project imports
#
from moneypools.models import (
    BankAccount,
    Budget,
    Transaction,
    TransactionAllocation,
)
from moneypools.service import _locking
from moneypools.service import budget as budget_svc
from moneypools.service import funding as funding_svc
from moneypools.service import internal_transaction as internal_transaction_svc
from moneypools.service import sync_scrape as sync_scrape_svc
from moneypools.service import transaction as transaction_svc
from moneypools.service import (
    transaction_allocation as transaction_allocation_svc,
)
from users.models import User

pytestmark = pytest.mark.django_db

# A locked row, identified by model name and primary key.
LockedRow = tuple[str, object]


########################################################################
########################################################################
#
def _row(obj: models.Model) -> LockedRow:
    """Return the `(model name, pk)` key recorded for a locked row."""
    return (type(obj).__name__, obj.pk)


####################################################################
#
@pytest.fixture
def locked_rows(mocker: MockerFixture) -> list[LockedRow]:
    """Record every row passed to `locked`, in call order.

    Service modules import `locked` by name, so the wrapper is patched
    into `_locking` (which `locked_many` calls through) and into every
    service module that imports it.

    Returns:
        The list the wrapper appends `(model name, pk)` tuples to.
    """
    rows: list[LockedRow] = []
    real_locked = _locking.locked

    def _record(obj: models.Model) -> models.Model:
        rows.append(_row(obj))
        return real_locked(obj)

    for module in (
        _locking,
        transaction_allocation_svc,
        transaction_svc,
        internal_transaction_svc,
        sync_scrape_svc,
    ):
        if hasattr(module, "locked"):
            mocker.patch.object(module, "locked", side_effect=_record)
    return rows


####################################################################
#
@pytest.fixture
def account(bank_account_factory: Callable[..., BankAccount]) -> BankAccount:
    """A bank account with a $100 Unallocated balance."""
    return bank_account_factory(
        available_balance=Money(100, "USD"),
        posted_balance=Money(100, "USD"),
    )


####################################################################
#
@pytest.fixture
def goal(account: BankAccount, budget_factory: Callable[..., Budget]) -> Budget:
    """A zero-balance fixed-amount Goal budget on `account`."""
    return budget_factory(
        bank_account=account,
        balance=Money(0, "USD"),
        budget_type=Budget.BudgetType.GOAL,
        funding_type=Budget.FundingType.FIXED_AMOUNT,
        funding_amount=Money(10, "USD"),
        target_balance=Money(100, "USD"),
    )


####################################################################
#
@pytest.fixture
def unallocated(account: BankAccount) -> Budget:
    """The Unallocated budget of `account`."""
    budget = account.unallocated_budget
    assert budget is not None
    return budget


########################################################################
########################################################################
#
class TestTransactionAllocationLocking:
    """Row locks taken by service/transaction_allocation.py."""

    ####################################################################
    #
    def test_create_locks_budget(
        self,
        account: BankAccount,
        goal: Budget,
        transaction_factory: Callable[..., Transaction],
        locked_rows: list[LockedRow],
    ) -> None:
        """
        GIVEN: a posted transaction and a Goal budget
        WHEN:  an allocation is created against the Goal
        THEN:  the Goal's row is re-read under a row lock before its
               balance changes
        """
        tx = transaction_factory(bank_account=account, amount=-5)
        locked_rows.clear()

        transaction_allocation_svc.create(
            transaction=tx, budget=goal, amount=Money(-5, "USD")
        )

        assert _row(goal) in locked_rows

    ####################################################################
    #
    def test_update_amount_locks_budget_then_allocation(
        self,
        account: BankAccount,
        unallocated: Budget,
        transaction_factory: Callable[..., Transaction],
        locked_rows: list[LockedRow],
    ) -> None:
        """
        GIVEN: a transaction whose allocation targets Unallocated
        WHEN:  the allocation's amount is changed
        THEN:  the budget row and then the allocation row are re-read
               under row locks
        """
        tx = transaction_factory(bank_account=account, amount=-5)
        alloc = TransactionAllocation.objects.get(transaction=tx)
        locked_rows.clear()

        transaction_allocation_svc.update_amount(alloc, Money(-7, "USD"))

        assert locked_rows[:2] == [_row(unallocated), _row(alloc)]

    ####################################################################
    #
    def test_delete_locks_budget_then_allocation(
        self,
        account: BankAccount,
        unallocated: Budget,
        transaction_factory: Callable[..., Transaction],
        locked_rows: list[LockedRow],
    ) -> None:
        """
        GIVEN: a transaction whose allocation targets Unallocated
        WHEN:  the allocation is deleted
        THEN:  the budget row and then the allocation row are re-read
               under row locks
        """
        tx = transaction_factory(bank_account=account, amount=-5)
        alloc = TransactionAllocation.objects.get(transaction=tx)
        expected = [_row(unallocated), _row(alloc)]
        locked_rows.clear()

        transaction_allocation_svc.delete(alloc)

        assert locked_rows[:2] == expected


########################################################################
########################################################################
#
class TestTransactionLocking:
    """Row locks taken by service/transaction.py."""

    ####################################################################
    #
    def test_create_locks_account_before_budget(
        self,
        account: BankAccount,
        unallocated: Budget,
        locked_rows: list[LockedRow],
    ) -> None:
        """
        GIVEN: a bank account
        WHEN:  a transaction is created
        THEN:  the account row is locked before the Unallocated budget
               row (lock order bank_account -> budget)
        """
        transaction_svc.create(
            bank_account=account,
            amount=Money(-5, "USD"),
            posted_date=datetime(2026, 3, 1, tzinfo=UTC),
            raw_description="COFFEE",
        )

        assert locked_rows == [_row(account), _row(unallocated)]

    ####################################################################
    #
    def test_delete_locks_account_transaction_then_budget(
        self,
        account: BankAccount,
        unallocated: Budget,
        transaction_factory: Callable[..., Transaction],
        locked_rows: list[LockedRow],
    ) -> None:
        """
        GIVEN: a transaction allocated to Unallocated
        WHEN:  the transaction is deleted
        THEN:  rows are locked in the order account, transaction,
               budget
        """
        tx = transaction_factory(bank_account=account, amount=-5)
        expected = [_row(account), _row(tx), _row(unallocated)]
        locked_rows.clear()

        transaction_svc.delete(tx)

        assert locked_rows[:3] == expected

    ####################################################################
    #
    def test_delete_split_locks_budgets_in_id_order(
        self,
        account: BankAccount,
        unallocated: Budget,
        goal: Budget,
        transaction_factory: Callable[..., Transaction],
        locked_rows: list[LockedRow],
    ) -> None:
        """
        GIVEN: a transaction split between a Goal and Unallocated
        WHEN:  the transaction is deleted
        THEN:  rows are locked in the order account, transaction, then
               both budgets in `id` order
        """
        tx = transaction_factory(bank_account=account, amount=-10)
        transaction_svc.split(tx, {str(goal.id): Decimal("4")})
        budgets = sorted([unallocated, goal], key=lambda b: str(b.id))
        expected = [_row(account), _row(tx)] + [_row(b) for b in budgets]
        locked_rows.clear()

        transaction_svc.delete(tx)

        assert locked_rows[:4] == expected

    def test_split_locks_transaction_then_budgets_in_id_order(
        self,
        account: BankAccount,
        unallocated: Budget,
        goal: Budget,
        transaction_factory: Callable[..., Transaction],
        locked_rows: list[LockedRow],
    ) -> None:
        """
        GIVEN: a posted transaction allocated to Unallocated
        WHEN:  it is split between a Goal and Unallocated
        THEN:  the transaction row is locked first, then every budget
               the split touches in `id` order
        """
        tx = transaction_factory(bank_account=account, amount=-10)
        locked_rows.clear()

        transaction_svc.split(tx, {str(goal.id): Decimal("4")})

        budgets = sorted([unallocated, goal], key=lambda b: str(b.id))
        assert locked_rows[:3] == [_row(tx)] + [_row(b) for b in budgets]


########################################################################
########################################################################
#
class TestInternalTransactionLocking:
    """Row locks taken by service/internal_transaction.py."""

    ####################################################################
    #
    def test_create_locks_both_budgets_in_id_order(
        self,
        account: BankAccount,
        unallocated: Budget,
        goal: Budget,
        user: User,
        locked_rows: list[LockedRow],
    ) -> None:
        """
        GIVEN: two budgets on one account
        WHEN:  money is transferred between them
        THEN:  both budget rows are locked in `id` order
        """
        internal_transaction_svc.create(
            bank_account=account,
            src_budget=unallocated,
            dst_budget=goal,
            amount=Money(10, "USD"),
            actor=user,
        )

        budgets = sorted([unallocated, goal], key=lambda b: str(b.id))
        assert locked_rows == [_row(b) for b in budgets]

    ####################################################################
    #
    def test_delete_locks_budgets_then_transfer(
        self,
        account: BankAccount,
        unallocated: Budget,
        goal: Budget,
        user: User,
        locked_rows: list[LockedRow],
    ) -> None:
        """
        GIVEN: a transfer between two budgets
        WHEN:  the transfer is deleted
        THEN:  both budget rows are locked in `id` order, then the
               transfer row
        """
        itx = internal_transaction_svc.create(
            bank_account=account,
            src_budget=unallocated,
            dst_budget=goal,
            amount=Money(10, "USD"),
            actor=user,
        )
        budgets = sorted([unallocated, goal], key=lambda b: str(b.id))
        expected = [_row(b) for b in budgets] + [_row(itx)]
        locked_rows.clear()

        internal_transaction_svc.delete(itx)

        assert locked_rows == expected


########################################################################
########################################################################
#
class TestBudgetLocking:
    """Row locks taken by service/budget.py."""

    ####################################################################
    #
    def test_update_locks_budget(
        self, goal: Budget, locked_rows: list[LockedRow]
    ) -> None:
        """
        GIVEN: a Goal budget
        WHEN:  its name is changed
        THEN:  the budget row is re-read under a row lock before the
               full-row save
        """
        budget_svc.update(goal, name="Renamed")

        assert locked_rows == [_row(goal)]

    ####################################################################
    #
    def test_archive_locks_budget_and_unallocated(
        self,
        account: BankAccount,
        unallocated: Budget,
        goal: Budget,
        user: User,
        locked_rows: list[LockedRow],
    ) -> None:
        """
        GIVEN: a Goal budget with no balance
        WHEN:  it is archived
        THEN:  the Goal and Unallocated rows are locked in `id` order
        """
        budget_svc.archive(goal, actor=user)

        budgets = sorted([unallocated, goal], key=lambda b: str(b.id))
        assert locked_rows[:2] == [_row(b) for b in budgets]

    ####################################################################
    #
    def test_delete_locks_budget_and_unallocated(
        self,
        account: BankAccount,
        unallocated: Budget,
        goal: Budget,
        user: User,
        locked_rows: list[LockedRow],
    ) -> None:
        """
        GIVEN: a Goal budget with no balance
        WHEN:  it is deleted
        THEN:  the Goal and Unallocated rows are locked in `id` order
        """
        budgets = sorted([unallocated, goal], key=lambda b: str(b.id))
        expected = [_row(b) for b in budgets]

        budget_svc.delete(goal, actor=user)

        assert locked_rows[:2] == expected


########################################################################
########################################################################
#
class TestFundingLocking:
    """Row locks taken by service/funding.py."""

    ####################################################################
    #
    def test_fund_event_locks_source_and_target(
        self,
        make_account: Callable[..., BankAccount],
        system_user: User,
        locked_rows: list[LockedRow],
    ) -> None:
        """
        GIVEN: a Goal budget with a fund event due today
        WHEN:  funding runs
        THEN:  Unallocated and the Goal are locked in `id` order before
               the transfer amount is computed
        """
        today = date(2026, 3, 1)
        account = make_account(posted_through=today)
        unallocated = account.unallocated_budget
        assert unallocated is not None
        goal = budget_svc.create(
            bank_account=account,
            name="Sneakers",
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(300, "USD"),
            funding_amount=Money(50, "USD"),
            funding_schedule=recurrence.Recurrence(
                dtstart=datetime(2026, 1, 1),
                rrules=[recurrence.Rule(recurrence.MONTHLY)],
            ),
        )
        Budget.objects.filter(pkid=goal.pkid).update(
            last_funded_on=date(2026, 2, 28)
        )

        report = funding_svc.fund_account(account, today, system_user)

        assert report.transfers == 1
        budgets = sorted([unallocated, goal], key=lambda b: str(b.id))
        assert locked_rows[:2] == [_row(b) for b in budgets]


########################################################################
########################################################################
#
class TestSyncScrapeLocking:
    """Row locks taken by service/sync_scrape.py."""

    ####################################################################
    #
    def test_sync_locks_account_then_unallocated(
        self,
        account: BankAccount,
        unallocated: Budget,
        mock_send_notification_now: object,
        locked_rows: list[LockedRow],
    ) -> None:
        """
        GIVEN: a bank account
        WHEN:  a scrape snapshot with no transactions is synced
        THEN:  the account row and then the Unallocated row are
               re-read under row locks
        """
        payload = sync_scrape_svc.ScrapeSyncPayload(
            scraped_at=datetime(2026, 5, 19, 12, 0, tzinfo=UTC),
            ending_balance=Money(100, "USD"),
            transactions=[],
        )

        sync_scrape_svc.sync_scrape(account, payload)

        assert locked_rows[:2] == [_row(account), _row(unallocated)]
