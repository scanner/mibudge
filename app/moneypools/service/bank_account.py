"""
BankAccount service -- Phase 5.

Operations:
    create(bank, name, account_type, owners, **kwargs)
        Creates the account, adds owners, creates the Unallocated budget,
        and back-links unallocated_budget_id.  Logic moved from the
        bank_account_post_save signal.

    update(account, **changes)
        Applies arbitrary field changes under a bank account lock.

    rename(account, name)
        Updates the name field under a bank account lock.

    delete(account)
        Deletes the account; cascade handles related budgets and transactions.
"""

# system imports
#
from datetime import UTC, datetime
from typing import Any

# Project imports
#
from common.locks import acquire_lock

# 3rd party imports
#
from django.db import transaction as db_transaction

from moneypools.models import Bank, BankAccount, Budget
from users.models import User


########################################################################
########################################################################
#
def create(
    bank: Bank,
    name: str,
    account_type: str,
    owners: list[User] | None = None,
    **kwargs: Any,
) -> BankAccount:
    """Create a bank account, add owners, and seed the Unallocated budget.

    Fires bank_account_pre_save (currency alignment) then creates the
    "Unallocated" budget whose initial balance matches the account's
    available_balance, back-linking unallocated_budget_id without
    triggering an extra save signal on the account.

    Args:
        bank: The Bank this account belongs to.
        name: Human-readable account name.
        account_type: One of BankAccount.BankAccountType values.
        owners: Users to add as account owners.  Defaults to none.
        **kwargs: Additional BankAccount field values (account_number,
            currency, posted_balance, available_balance, etc.).

    Returns:
        The saved BankAccount instance with unallocated_budget set.
    """
    with db_transaction.atomic():
        account = BankAccount(
            bank=bank,
            name=name,
            account_type=account_type,
            **kwargs,
        )
        account.save()

        if owners:
            account.owners.set(owners)

        unallocated = Budget(
            name="Unallocated",
            bank_account=account,
            target_date=datetime.now(UTC).date(),
            balance=account.available_balance,
        )
        unallocated.save()
        BankAccount.objects.filter(id=account.id).update(
            unallocated_budget_id=unallocated.id
        )
        account.unallocated_budget = unallocated

    return account


########################################################################
########################################################################
#
def update(account: BankAccount, **changes: Any) -> BankAccount:
    """Update mutable fields on an existing bank account.

    Acquires the account lock, applies *changes*, and saves.  Intended
    for API-level updates where only non-financial fields (name,
    account_number) are modified.

    Args:
        account: The BankAccount instance to update.
        **changes: Field-value pairs to apply.

    Returns:
        The updated BankAccount instance (refreshed from DB).
    """
    with acquire_lock(account.lock_key):
        with db_transaction.atomic():
            for field, value in changes.items():
                setattr(account, field, value)
            account.save()

    account.refresh_from_db()
    return account


####################################################################
#
def rename(account: BankAccount, name: str) -> BankAccount:
    """Rename a bank account.

    Args:
        account: The BankAccount to rename.
        name: The new name.

    Returns:
        The updated BankAccount instance (refreshed from DB).
    """
    with acquire_lock(account.lock_key):
        with db_transaction.atomic():
            account.name = name
            account.save()

    account.refresh_from_db()
    return account


########################################################################
########################################################################
#
def delete(account: BankAccount) -> None:
    """Delete a bank account and all its related objects.

    Cascade deletes all budgets, transactions, and allocations owned
    by the account.

    Args:
        account: The BankAccount to delete.
    """
    account.delete()
