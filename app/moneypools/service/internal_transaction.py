"""
InternalTransaction service -- Phase 1.

Operations:
    create(bank_account, src_budget, dst_budget, amount, actor)
        Sorted budget locks via ExitStack, one atomic().
        Snapshots src_budget_balance / dst_budget_balance on the row.
    delete(internal_transaction)
        Reverses balance changes under sorted budget locks.
"""

# system imports
#
from contextlib import ExitStack

# Project imports
#
from common.locks import acquire_lock

# 3rd party imports
#
from django.db import transaction as db_transaction
from djmoney.money import Money

from moneypools.models import BankAccount, Budget, InternalTransaction
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
) -> InternalTransaction:
    """Create an internal transaction, transferring funds between two budgets.

    Acquires sorted budget locks to prevent deadlocks, then inside a
    single atomic block refreshes both budgets, debits src, credits dst,
    records balance snapshots, and inserts the InternalTransaction row.

    Args:
        bank_account: The bank account both budgets belong to.
        src_budget: The budget to debit.
        dst_budget: The budget to credit.
        amount: A positive Money value to transfer.
        actor: The user initiating the transfer.

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
            return InternalTransaction.objects.create(  # type: ignore[misc]
                bank_account=bank_account,
                src_budget=src_budget,
                dst_budget=dst_budget,
                amount=amount,
                actor=actor,
                src_budget_balance=src_budget.balance,
                dst_budget_balance=dst_budget.balance,
            )


########################################################################
########################################################################
#
def delete(internal_transaction: InternalTransaction) -> None:
    """Delete an internal transaction, reversing the budget balance changes.

    Acquires sorted budget locks, refreshes both budgets, reverses the
    debit/credit applied on creation, and removes the row.

    Args:
        internal_transaction: The InternalTransaction to reverse and delete.
    """
    src_budget = internal_transaction.src_budget
    dst_budget = internal_transaction.dst_budget
    amount = internal_transaction.amount

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
