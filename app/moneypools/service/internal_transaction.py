"""
InternalTransaction service -- Phase 1.

Operations:
    create(bank_account, src_budget, dst_budget, amount, actor, effective_date)
        Sorted budget locks via ExitStack, one atomic().
        Snapshots src_budget_balance / dst_budget_balance on the row.
        Triggers running-balance recalculation for both budgets.
    delete(internal_transaction)
        Reverses balance changes under sorted budget locks.
        Triggers running-balance recalculation for both budgets.
"""

# system imports
#
from contextlib import ExitStack
from datetime import UTC, datetime

# Project imports
#
from common.locks import acquire_lock

# 3rd party imports
#
from django.db import transaction as db_transaction
from djmoney.money import Money

from moneypools.models import BankAccount, Budget, InternalTransaction
from moneypools.service import transaction_allocation as alloc_svc
from users.models import User


########################################################################
########################################################################
#
def create(
    bank_account: BankAccount,
    src_budget: Budget,
    dst_budget: Budget,
    amount: Money,
    actor: User,
    effective_date: datetime | None = None,
) -> InternalTransaction:
    """Create an internal transaction, transferring funds between two budgets.

    Acquires sorted budget locks to prevent deadlocks, then inside a
    single atomic block refreshes both budgets, debits src, credits dst,
    records balance snapshots, and inserts the InternalTransaction row.
    After the row is committed, recalculates running budget_balance
    snapshots for both affected budgets starting from effective_date.

    Args:
        bank_account: The bank account both budgets belong to.
        src_budget: The budget to debit.
        dst_budget: The budget to credit.
        amount: A positive Money value to transfer.
        actor: The user initiating the transfer.
        effective_date: Economic datetime of the transfer.  Defaults to
            None, which causes the model to fall back to created_at via
            COALESCE in running-balance queries.  Backfill passes the
            period-boundary datetime so the ITx slots correctly into the
            historical timeline.

    Returns:
        The newly created InternalTransaction instance.

    Raises:
        ValueError: If amount is not positive.
    """
    if amount.amount <= 0:
        raise ValueError(f"Amount must be positive: {amount}")

    budgets = sorted([src_budget, dst_budget], key=lambda b: str(b.id))
    with ExitStack() as stack:
        for b in budgets:
            stack.enter_context(acquire_lock(b.lock_key))

        with db_transaction.atomic():
            src_budget.refresh_from_db()
            dst_budget.refresh_from_db()

            src_budget.balance -= amount
            dst_budget.balance += amount
            src_budget.save()
            dst_budget.save()

            # djmoney stubs type MoneyField.__set__ as accepting
            # str|float|Decimal|Combinable but not Money directly.
            # Money is accepted at runtime; suppress the false positive.
            #
            itx = InternalTransaction.objects.create(  # type: ignore[misc]
                bank_account=bank_account,
                src_budget=src_budget,
                dst_budget=dst_budget,
                amount=amount,
                actor=actor,
                src_budget_balance=src_budget.balance,
                dst_budget_balance=dst_budget.balance,
                effective_date=effective_date
                if effective_date is not None
                else datetime.now(UTC),
            )

    # Recalculate outside the lock so we don't hold it during the full
    # forward scan.
    from_dt = itx.effective_date
    alloc_svc.recalculate_from_dt(src_budget, from_dt)
    alloc_svc.recalculate_from_dt(dst_budget, from_dt)
    alloc_svc.recalculate_itx_snapshots_from_dt(src_budget, from_dt)
    alloc_svc.recalculate_itx_snapshots_from_dt(dst_budget, from_dt)

    return itx


########################################################################
########################################################################
#
def delete(internal_transaction: InternalTransaction) -> None:
    """Delete an internal transaction, reversing the budget balance changes.

    Acquires sorted budget locks, refreshes both budgets, reverses the
    debit/credit applied on creation, and removes the row.  After the
    row is deleted, recalculates running budget_balance snapshots for
    both affected budgets.

    Args:
        internal_transaction: The InternalTransaction to reverse and delete.
    """
    src_budget = internal_transaction.src_budget
    dst_budget = internal_transaction.dst_budget
    amount = internal_transaction.amount
    from_dt = internal_transaction.effective_date

    budgets = sorted([src_budget, dst_budget], key=lambda b: str(b.id))
    with ExitStack() as stack:
        for b in budgets:
            stack.enter_context(acquire_lock(b.lock_key))

        with db_transaction.atomic():
            src_budget.refresh_from_db()
            dst_budget.refresh_from_db()

            src_budget.balance += amount
            dst_budget.balance -= amount
            src_budget.save()
            dst_budget.save()

            internal_transaction.delete()

    alloc_svc.recalculate_from_dt(src_budget, from_dt)
    alloc_svc.recalculate_from_dt(dst_budget, from_dt)
    alloc_svc.recalculate_itx_snapshots_from_dt(src_budget, from_dt)
    alloc_svc.recalculate_itx_snapshots_from_dt(dst_budget, from_dt)
