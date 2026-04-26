"""
Transaction service -- Phase 4.

Operations:
    create(bank_account, amount, posted_date, raw_description, **kwargs)
        Locks the bank account, applies bank-balance math, saves the
        transaction, creates a default allocation to Unallocated, and
        enqueues the cross-account linker via on_commit.

        ``posted_date`` is always the bank-supplied settlement datetime.
        ``transaction_date`` (optional kwarg) is the purchase datetime;
        if omitted the service derives it via
        ``description_utils.parse_transaction_date``.

    update(transaction, **changes)
        Applies mutable field changes (transaction_type, memo,
        description) without touching bank or budget balances.

    delete(transaction)
        Reverses bank account balances, deletes each allocation via
        TransactionAllocationService (reversing budget balances), then
        deletes the transaction.

    split(transaction, splits)
        Validates business rules, acquires a transaction lock, then
        reconciles TransactionAllocation objects to match the declared
        split map.  Any remainder goes to the unallocated budget.
        Returns the final list of allocations.
"""

# system imports
#
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

# 3rd party imports
#
import moneyed

# Project imports
#
from common.locks import acquire_lock
from django.db import transaction as db_transaction

from moneypools.description_utils import parse_transaction_date
from moneypools.models import (
    BankAccount,
    Budget,
    Transaction,
    TransactionAllocation,
)
from moneypools.service import (
    transaction_allocation as transaction_allocation_svc,
)


########################################################################
########################################################################
#
def create(
    bank_account: BankAccount,
    amount: moneyed.Money,
    posted_date: datetime,
    raw_description: str,
    transaction_date: datetime | None = None,
    **kwargs: Any,
) -> Transaction:
    """Create a transaction, apply bank-balance math, and seed the default allocation.

    Args:
        bank_account: The bank account this transaction belongs to.
        amount: Signed transaction amount (negative for debits).
        posted_date: Bank-supplied settlement datetime (always required).
        raw_description: Unedited description from the bank feed.
        transaction_date: Purchase datetime.  When omitted (the common
            importer case), derived from the MM/DD pattern embedded in
            ``raw_description`` via ``parse_transaction_date``; falls
            back to ``posted_date`` when no parseable date is found.
        **kwargs: Additional Transaction field values (transaction_type,
            pending, memo, description, etc.).

    Returns:
        The saved Transaction instance.
    """
    pending: bool = kwargs.pop("pending", False)

    if isinstance(posted_date, str):
        posted_date = datetime.fromisoformat(posted_date.replace("Z", "+00:00"))

    if transaction_date is None:
        parsed = parse_transaction_date(
            raw_description, posted_date.astimezone(UTC).date()
        )
        transaction_date = datetime(
            parsed.year,
            parsed.month,
            parsed.day,
            tzinfo=UTC,
        )

    with acquire_lock(bank_account.lock_key):
        with db_transaction.atomic():
            bank_account.refresh_from_db()
            bank_account.available_balance += amount
            if not pending:
                bank_account.posted_balance += amount
            bank_account.save()

            tx = Transaction(
                bank_account=bank_account,
                amount=amount,  # type: ignore[misc]
                posted_date=posted_date,
                transaction_date=transaction_date,
                raw_description=raw_description,
                pending=pending,
                bank_account_available_balance=bank_account.available_balance,
                bank_account_posted_balance=bank_account.posted_balance,
                **kwargs,
            )
            tx.save()

            unallocated = bank_account.unallocated_budget
            transaction_allocation_svc.create(
                transaction=tx,
                budget=unallocated,
                amount=amount,
            )

            if tx.linked_transaction_id is None:
                # Import deferred to avoid the service → tasks → linking → models
                # circular import that fires during Django app ready().
                from moneypools.tasks import attempt_link_transaction

                tx_id = str(tx.id)
                db_transaction.on_commit(
                    lambda: attempt_link_transaction.delay(tx_id)
                )

    return tx


########################################################################
########################################################################
#
def update(transaction: Transaction, **changes: Any) -> Transaction:
    """Update fields on an existing transaction.

    Handles the pending → posted transition by crediting the bank
    account's posted_balance.  Other mutable fields (transaction_type,
    memo, description) are applied without balance changes.

    Args:
        transaction: The Transaction instance to update.
        **changes: Field-value pairs to apply.

    Returns:
        The updated Transaction instance (refreshed from DB).

    Raises:
        ValueError: If any key in changes would alter amount,
            bank_account, or raw_description.
    """
    immutable = {"bank_account", "raw_description"}
    bad = immutable & changes.keys()
    if bad:
        raise ValueError(
            f"Field(s) {sorted(bad)} cannot be changed after creation."
        )

    new_amount: moneyed.Money | None = changes.get("amount")
    new_pending = changes.get("pending")
    amount_changed = new_amount is not None and new_amount != transaction.amount
    pending_to_posted = new_pending is False and transaction.pending is True

    if amount_changed or pending_to_posted:
        bank_account = transaction.bank_account
        old_amount = transaction.amount
        was_pending = transaction.pending
        final_amount = new_amount if amount_changed else old_amount
        will_be_pending = (
            new_pending if new_pending is not None else was_pending
        )

        with acquire_lock(bank_account.lock_key):
            with db_transaction.atomic():
                bank_account.refresh_from_db()

                # Always reverse the old available contribution and apply new.
                if amount_changed:
                    bank_account.available_balance -= old_amount
                    bank_account.available_balance += final_amount

                # Reverse old posted contribution; apply new posted contribution.
                if not was_pending:
                    bank_account.posted_balance -= old_amount
                if not will_be_pending:
                    bank_account.posted_balance += final_amount

                bank_account.save()
                for field, value in changes.items():
                    setattr(transaction, field, value)
                transaction.save()
    else:
        for field, value in changes.items():
            setattr(transaction, field, value)
        transaction.save()

    transaction.refresh_from_db()
    return transaction


########################################################################
########################################################################
#
def delete(transaction: Transaction) -> None:
    """Delete a transaction, reversing bank and budget balances.

    Deletes each allocation via TransactionAllocationService (which
    reverses the affected budget balances), reverses the bank account
    balances, then deletes the transaction row.

    Args:
        transaction: The Transaction to delete.
    """
    bank_account = transaction.bank_account
    allocations = list(
        TransactionAllocation.objects.filter(
            transaction=transaction
        ).select_related("budget")
    )

    with acquire_lock(bank_account.lock_key):
        with db_transaction.atomic():
            for alloc in allocations:
                if alloc.budget is not None:
                    transaction_allocation_svc.delete(alloc)

            bank_account.refresh_from_db()
            bank_account.available_balance -= transaction.amount
            if not transaction.pending:
                bank_account.posted_balance -= transaction.amount
            bank_account.save()

            transaction.delete()


########################################################################
########################################################################
#
def split(
    transaction: Transaction,
    splits: dict[str, Decimal],
) -> list[TransactionAllocation]:
    """Reconcile transaction allocations to match a declared split map.

    Validates business rules, then creates, updates, or deletes
    TransactionAllocation objects so that each budget in *splits*
    receives exactly its declared (signed) amount.  Any remainder
    (abs(transaction.amount) minus sum of split amounts) is assigned
    to the account's unallocated budget.

    Args:
        transaction: The Transaction to split.
        splits: Map of budget UUID string → absolute (positive) amount.
            An empty dict moves the full amount to the unallocated budget.

    Returns:
        List of all TransactionAllocation objects for this transaction
        after reconciliation, ordered by created_at.

    Raises:
        ValueError: If any budget UUID is unknown, belongs to a
            different bank account, has a non-positive amount, or if
            the total exceeds the transaction amount.
    """
    account = transaction.bank_account
    tx_abs = abs(transaction.amount.amount)
    is_debit = transaction.amount.amount < 0
    currency = transaction.amount.currency

    _validate_splits(splits, account, tx_abs)

    budget_ids = list(splits.keys())
    budgets_by_id: dict[str, Budget] = {}
    if budget_ids:
        for b in Budget.objects.filter(id__in=budget_ids):
            budgets_by_id[str(b.id)] = b

    unallocated = account.unallocated_budget

    with acquire_lock(transaction.lock_key):
        with db_transaction.atomic():
            existing = list(
                TransactionAllocation.objects.filter(
                    transaction=transaction
                ).select_related("budget")
            )
            existing_by_budget: dict[str, TransactionAllocation] = {}
            for alloc in existing:
                if alloc.budget is not None:
                    existing_by_budget[str(alloc.budget.id)] = alloc

            touched_ids: set[str] = set()

            for budget_id, abs_amount in splits.items():
                signed = moneyed.Money(
                    -abs_amount if is_debit else abs_amount, currency
                )
                budget = budgets_by_id[budget_id]

                if budget_id in existing_by_budget:
                    alloc = existing_by_budget[budget_id]
                    if alloc.amount.amount != signed.amount:
                        transaction_allocation_svc.update_amount(alloc, signed)
                else:
                    transaction_allocation_svc.create(
                        transaction=transaction,
                        budget=budget,
                        amount=signed,
                    )
                touched_ids.add(budget_id)

            # Compute and apply unallocated remainder.
            split_total = sum(splits.values(), Decimal("0"))
            remainder = tx_abs - split_total
            unalloc_key = str(unallocated.id) if unallocated else None

            if remainder > 0 and unallocated:
                signed_remainder = moneyed.Money(
                    -remainder if is_debit else remainder, currency
                )
                if unalloc_key and unalloc_key in existing_by_budget:
                    alloc = existing_by_budget[unalloc_key]
                    if alloc.amount.amount != signed_remainder.amount:
                        transaction_allocation_svc.update_amount(
                            alloc, signed_remainder
                        )
                else:
                    transaction_allocation_svc.create(
                        transaction=transaction,
                        budget=unallocated,
                        amount=signed_remainder,
                    )
                if unalloc_key:
                    touched_ids.add(unalloc_key)
            elif (
                unalloc_key
                and unalloc_key in existing_by_budget
                and remainder == 0
            ):
                # Nothing goes to unallocated; delete the existing allocation.
                pass  # handled in the cleanup loop below

            # Delete allocations no longer needed.
            for alloc in existing:
                budget_key = str(alloc.budget.id) if alloc.budget else None
                if budget_key not in touched_ids:
                    transaction_allocation_svc.delete(alloc)

    return list(
        TransactionAllocation.objects.filter(transaction=transaction)
        .select_related("budget")
        .order_by("created_at")
    )


########################################################################
########################################################################
#
def _validate_splits(
    splits: dict[str, Decimal],
    account: BankAccount,
    tx_abs: Decimal,
) -> None:
    """Raise ValueError if the splits map violates business rules.

    Args:
        splits: Map of budget UUID string → absolute amount.
        account: The bank account the transaction belongs to.
        tx_abs: Absolute transaction amount.

    Raises:
        ValueError: On unknown budgets, wrong-account budgets, non-positive
            amounts, or a total that exceeds the transaction amount.
    """
    if not splits:
        return

    budget_ids = list(splits.keys())
    budgets = list(Budget.objects.filter(id__in=budget_ids))
    found_ids = {str(b.id) for b in budgets}
    missing = set(budget_ids) - found_ids
    if missing:
        raise ValueError(f"Unknown budget IDs: {', '.join(sorted(missing))}")

    wrong_account = [
        str(b.id) for b in budgets if b.bank_account_id != account.id
    ]
    if wrong_account:
        raise ValueError(
            "Budgets do not belong to the same bank account as the "
            f"transaction: {', '.join(sorted(wrong_account))}"
        )

    total = Decimal("0")
    for budget_id, amount in splits.items():
        if amount <= 0:
            raise ValueError(f"Amount for budget {budget_id} must be positive.")
        total += amount

    if total > tx_abs:
        raise ValueError(
            f"Split total ({total}) exceeds transaction amount ({tx_abs})."
        )
