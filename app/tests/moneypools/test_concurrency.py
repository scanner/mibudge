#!/usr/bin/env python
#
"""
Concurrency tests for balance updates.

Each test races two writers the way two HTTP requests race in
production: every writer runs inside its own outer `atomic()`, as
`ATOMIC_REQUESTS` wraps a request, so the service's own `atomic()` is a
savepoint and its Redis lock is released before the outer transaction
commits.

The tests run on the default SQLite test database (a file opened with
`BEGIN IMMEDIATE`, see `common.db`) and, in the Postgres test mode
(`MIBUDGE_TEST_DATABASE_URL`), on Postgres.  On Postgres the second
writer waits on the row lock taken by `_locking.locked`; on SQLite it
waits at `BEGIN` for the database write lock.
"""

# system imports
#
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

# 3rd party imports
#
import pytest
from django.db import connection
from django.db import transaction as db_transaction
from django.db.transaction import TransactionManagementError
from djmoney.money import Money
from pytest_mock import MockerFixture

# Project imports
#
from moneypools.models import BankAccount, Budget, Transaction
from moneypools.service import internal_transaction as internal_transaction_svc
from moneypools.service import transaction as transaction_svc
from moneypools.service import (
    transaction_allocation as transaction_allocation_svc,
)
from moneypools.service._locking import locked
from users.models import User

# `transaction=True` lets each thread's connection see committed rows;
# `serialized_rollback=True` restores migration-seeded rows (the funding
# system user) that the post-test flush would otherwise remove.
#
pytestmark = [
    pytest.mark.concurrency,
    pytest.mark.django_db(transaction=True, serialized_rollback=True),
]

# Upper bound for every wait, so a regression fails the test instead of
# hanging the run.
#
_TIMEOUT = 15.0

# How long thread B must stay unfinished on SQLite before A is released.
# Shorter than SQLite's 5 second busy timeout, so B is still waiting
# for the write lock rather than giving up.
#
_SQLITE_BLOCK_CHECK = 0.5


########################################################################
########################################################################
#
def _lock_waiters() -> int:
    """Return how many other backends are waiting on a Postgres lock."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_stat_activity"
            " WHERE datname = current_database()"
            " AND wait_event_type = 'Lock'"
            " AND pid <> pg_backend_pid()"
        )
        row = cursor.fetchone()
    assert row is not None
    return int(row[0])


########################################################################
########################################################################
#
def _wait_until_blocked(
    thread_b: threading.Thread,
    b_done: threading.Event,
    errors_b: list[BaseException],
) -> None:
    """Return once thread B is waiting for a lock held by thread A.

    Args:
        thread_b: The second writer's thread.
        b_done: Set when thread B exits.
        errors_b: Exceptions raised in thread B, for the failure message.
    """
    if connection.vendor == "postgresql":
        deadline = time.monotonic() + _TIMEOUT
        while _lock_waiters() == 0:
            assert thread_b.is_alive(), (
                f"thread B finished without blocking: {errors_b}"
            )
            assert time.monotonic() < deadline, "thread B never blocked"
            time.sleep(0.01)
        return

    # SQLite has no view of lock waiters.  While A holds the database
    # write lock, B cannot get past `BEGIN IMMEDIATE`, so B still being
    # unfinished after a bounded wait stands in for "B is blocked".
    #
    assert not b_done.wait(_SQLITE_BLOCK_CHECK), (
        f"thread B finished without blocking: {errors_b}"
    )


########################################################################
########################################################################
#
def _race(
    first: Callable[[], object], second: Callable[[], object]
) -> tuple[list[BaseException], list[BaseException]]:
    """Run two writers so the second reads while the first is uncommitted.

    1. Thread A opens an outer `atomic()`, calls `first`, and keeps the
       transaction open once `first` returns.  Its Redis locks are
       released at that point; its row changes are not yet committed.
    2. Thread B opens an outer `atomic()` and calls `second`, which
       waits for a database lock held by A: a row lock on Postgres, the
       database write lock on SQLite.
    3. Once B is waiting, A commits, B proceeds, and both threads are
       joined.  B checks that its write completed only after A was
       released, so B read the balance A committed.

    Args:
        first: The writer run (and held open) by thread A.
        second: The writer run by thread B.

    Returns:
        The exceptions raised in thread A and in thread B.
    """
    first_done = threading.Event()
    release_first = threading.Event()
    b_done = threading.Event()
    errors_a: list[BaseException] = []
    errors_b: list[BaseException] = []

    def _thread_a() -> None:
        try:
            with db_transaction.atomic():
                first()
                first_done.set()
                if not release_first.wait(_TIMEOUT):
                    raise TimeoutError("thread A was never released")
        except BaseException as exc:
            errors_a.append(exc)
        finally:
            first_done.set()
            connection.close()

    def _thread_b() -> None:
        try:
            with db_transaction.atomic():
                second()
                if not release_first.is_set():
                    raise AssertionError(
                        "thread B wrote while thread A was uncommitted"
                    )
        except BaseException as exc:
            errors_b.append(exc)
        finally:
            connection.close()
            b_done.set()

    thread_a = threading.Thread(target=_thread_a, daemon=True)
    thread_b = threading.Thread(target=_thread_b, daemon=True)
    try:
        thread_a.start()
        assert first_done.wait(_TIMEOUT), "thread A did not finish its write"
        assert not errors_a, errors_a

        thread_b.start()
        _wait_until_blocked(thread_b, b_done, errors_b)
    finally:
        release_first.set()
        thread_a.join(_TIMEOUT)
        thread_b.join(_TIMEOUT)

    assert not thread_a.is_alive(), "thread A did not exit"
    assert not thread_b.is_alive(), "thread B did not exit"
    return errors_a, errors_b


####################################################################
#
@pytest.fixture(autouse=True)
def _no_link_task(mocker: MockerFixture) -> None:
    """Stub the linker task that `transaction_svc.create` enqueues.

    These tests commit for real, so `on_commit` callbacks run and would
    otherwise try to reach the Celery broker.
    """
    mocker.patch("moneypools.tasks.attempt_link_transaction.delay")


####################################################################
#
@pytest.fixture
def account(bank_account_factory: Callable[..., BankAccount]) -> BankAccount:
    """A committed bank account with $100 in Unallocated."""
    return bank_account_factory(
        available_balance=Money(100, "USD"),
        posted_balance=Money(100, "USD"),
    )


####################################################################
#
@pytest.fixture
def make_goal(
    account: BankAccount, budget_factory: Callable[..., Budget]
) -> Callable[[], Budget]:
    """Return a factory for zero-balance Goal budgets on `account`."""

    def _make() -> Budget:
        return budget_factory(
            bank_account=account,
            balance=Money(0, "USD"),
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            funding_amount=Money(10, "USD"),
            target_balance=Money(100, "USD"),
        )

    return _make


########################################################################
########################################################################
#
class TestConcurrentBalanceUpdates:
    """Two writers to one balance row both take effect."""

    ####################################################################
    #
    def test_concurrent_allocations_to_one_budget_both_apply(
        self,
        account: BankAccount,
        make_goal: Callable[[], Budget],
        transaction_factory: Callable[..., Transaction],
    ) -> None:
        """
        GIVEN: a Goal budget and two posted transactions
        WHEN:  two requests each allocate $10 to the Goal concurrently
        THEN:  the Goal's balance rises by $20
        """
        goal = make_goal()
        tx1 = transaction_factory(bank_account=account, amount=10)
        tx2 = transaction_factory(bank_account=account, amount=10)

        # Each thread gets its own Budget instance, as each request
        # would load its own copy of the row.
        #
        errors_a, errors_b = _race(
            lambda: transaction_allocation_svc.create(
                transaction=tx1,
                budget=Budget.objects.get(pk=goal.pk),
                amount=Money(10, "USD"),
            ),
            lambda: transaction_allocation_svc.create(
                transaction=tx2,
                budget=Budget.objects.get(pk=goal.pk),
                amount=Money(10, "USD"),
            ),
        )

        assert not errors_a and not errors_b, (errors_a, errors_b)
        goal.refresh_from_db()
        assert goal.balance == Money(20, "USD")

    ####################################################################
    #
    def test_concurrent_transaction_creates_both_apply_to_account(
        self, account: BankAccount
    ) -> None:
        """
        GIVEN: a bank account with $100 available
        WHEN:  two requests each create a -$10 transaction concurrently
        THEN:  the account's available and posted balances, and its
               Unallocated budget, all drop by $20
        """

        def _create() -> Transaction:
            return transaction_svc.create(
                bank_account=BankAccount.objects.get(pk=account.pk),
                amount=Money(-10, "USD"),
                posted_date=datetime(2026, 3, 1, tzinfo=UTC),
                raw_description="COFFEE",
            )

        errors_a, errors_b = _race(_create, _create)

        assert not errors_a and not errors_b, (errors_a, errors_b)
        account.refresh_from_db()
        assert account.available_balance == Money(80, "USD")
        assert account.posted_balance == Money(80, "USD")
        unallocated = account.unallocated_budget
        assert unallocated is not None
        assert unallocated.balance == Money(80, "USD")

    ####################################################################
    #
    def test_concurrent_transfers_from_one_budget_both_apply(
        self,
        account: BankAccount,
        make_goal: Callable[[], Budget],
        user: User,
    ) -> None:
        """
        GIVEN: $100 in Unallocated and two Goal budgets
        WHEN:  two requests each transfer $10 from Unallocated to a
               different Goal concurrently
        THEN:  Unallocated drops by $20 and each Goal rises by $10
        """
        goals = [make_goal(), make_goal()]
        unallocated = account.unallocated_budget
        assert unallocated is not None

        def _transfer(dst: Budget) -> Callable[[], object]:
            return lambda: internal_transaction_svc.create(
                bank_account=account,
                src_budget=Budget.objects.get(pk=unallocated.pk),
                dst_budget=Budget.objects.get(pk=dst.pk),
                amount=Money(10, "USD"),
                actor=user,
            )

        errors_a, errors_b = _race(_transfer(goals[0]), _transfer(goals[1]))

        assert not errors_a and not errors_b, (errors_a, errors_b)
        unallocated.refresh_from_db()
        assert unallocated.balance == Money(80, "USD")
        for goal in goals:
            goal.refresh_from_db()
            assert goal.balance == Money(10, "USD")

    ####################################################################
    #
    def test_concurrent_resolves_credit_posted_balance_once(
        self, account: BankAccount
    ) -> None:
        """
        GIVEN: a pending -$10 transaction on an account with $100 posted
        WHEN:  two requests resolve it to posted concurrently
        THEN:  posted_balance drops by $10 exactly once
        AND:   the second resolve raises ValueError
        """
        tx = transaction_svc.create(
            bank_account=account,
            amount=Money(-10, "USD"),
            posted_date=datetime(2026, 3, 1, tzinfo=UTC),
            raw_description="PENDING PURCHASE",
            pending=True,
        )

        # Each thread loads the still-pending row, as each request would.
        #
        def _resolve() -> Transaction:
            return transaction_svc.resolve_pending_to_posted(
                Transaction.objects.get(pk=tx.pk),
                new_posted_date=datetime(2026, 3, 2, tzinfo=UTC),
            )

        errors_a, errors_b = _race(_resolve, _resolve)

        assert not errors_a, errors_a
        assert len(errors_b) == 1
        assert isinstance(errors_b[0], ValueError)
        account.refresh_from_db()
        assert account.posted_balance == Money(90, "USD")


########################################################################
########################################################################
#
@pytest.mark.postgres
class TestLockedHelper:
    """Contract of `moneypools.service._locking.locked` on Postgres."""

    ####################################################################
    #
    def test_locked_requires_a_transaction(self, account: BankAccount) -> None:
        """
        GIVEN: a saved bank account
        WHEN:  `locked` is called outside `atomic()`
        THEN:  it raises TransactionManagementError, because a row lock
               would end with the statement
        """
        with pytest.raises(TransactionManagementError):
            locked(account)
