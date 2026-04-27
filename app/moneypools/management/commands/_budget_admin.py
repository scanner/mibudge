"""
Shared helpers for budget administration management commands.

Imported by clear_budget (and any future admin commands that operate on
budget data).  Not a management command itself.
"""

# system imports
#
from decimal import Decimal
from uuid import UUID

# 3rd party imports
#
from django.conf import settings
from django.core.management.base import CommandError
from django.db.models import Q

# Project imports
#
from moneypools.models import (
    BankAccount,
    Budget,
    InternalTransaction,
    Transaction,
    TransactionAllocation,
)
from moneypools.service import internal_transaction as internal_transaction_svc
from moneypools.service import transaction as transaction_svc
from users.models import User


########################################################################
########################################################################
#
def resolve_account(pattern: str) -> BankAccount:
    """Find the unique BankAccount matching *pattern*.

    Tries exact UUID match, then name substring, then UUID substring.

    Args:
        pattern: Full UUID, UUID prefix/substring, or name fragment.

    Returns:
        The matching BankAccount.

    Raises:
        CommandError: When zero or more than one account matches.
    """
    qs = BankAccount.objects.all()

    try:
        uid = UUID(pattern)
        exact = list(qs.filter(id=uid))
        if len(exact) == 1:
            return exact[0]
    except ValueError:
        pass

    matches = list(qs.filter(name__icontains=pattern))
    if not matches:
        matches = [a for a in qs.all() if pattern.lower() in str(a.id).lower()]

    if not matches:
        raise CommandError(f"No bank account matches {pattern!r}.")
    if len(matches) > 1:
        listing = "\n".join(f"  {a.name}  ({a.id})" for a in matches)
        raise CommandError(
            f"Multiple accounts match {pattern!r}:\n{listing}\n"
            "Provide a more specific pattern."
        )
    return matches[0]


########################################################################
########################################################################
#
def resolve_budget(
    pattern: str,
    account: BankAccount | None = None,
) -> Budget:
    """Find the unique Budget matching *pattern*.

    Tries exact UUID match, then name substring, then UUID substring.

    Args:
        pattern: Full UUID, UUID prefix/substring, or name fragment.
        account: If provided, restricts the search to this account.

    Returns:
        The matching Budget.

    Raises:
        CommandError: When zero or more than one budget matches.
    """
    qs = Budget.objects.select_related("bank_account")
    if account is not None:
        qs = qs.filter(bank_account=account)

    try:
        uid = UUID(pattern)
        exact = list(qs.filter(id=uid))
        if len(exact) == 1:
            return exact[0]
    except ValueError:
        pass

    matches = list(qs.filter(name__icontains=pattern))
    if not matches:
        all_budgets = list(qs.all())
        matches = [
            b for b in all_budgets if pattern.lower() in str(b.id).lower()
        ]

    if not matches:
        scope = f" in account '{account.name}'" if account else ""
        raise CommandError(f"No budget matches {pattern!r}{scope}.")
    if len(matches) > 1:
        listing = "\n".join(
            f"  {b.name}  ({b.id})  [{b.bank_account.name}]" for b in matches
        )
        raise CommandError(
            f"Multiple budgets match {pattern!r}:\n{listing}\n"
            "Provide a more specific pattern or use --account to narrow the scope."
        )
    return matches[0]


########################################################################
########################################################################
#
def count_allocations(budget: Budget) -> tuple[int, int]:
    """Return (allocation_row_count, distinct_transaction_count) for a budget.

    Args:
        budget: The budget to inspect.

    Returns:
        Tuple of (total allocation rows, distinct transactions referenced).
    """
    qs = TransactionAllocation.objects.filter(budget=budget)
    alloc_count = qs.count()
    tx_count = qs.values("transaction_id").distinct().count()
    return alloc_count, tx_count


########################################################################
########################################################################
#
def count_internal_transactions(budget: Budget) -> int:
    """Return the number of InternalTransactions that involve a budget.

    Counts rows where the budget appears as either src or dst.

    Args:
        budget: The budget to inspect.

    Returns:
        Number of InternalTransaction rows involving this budget.
    """
    return InternalTransaction.objects.filter(
        Q(src_budget=budget) | Q(dst_budget=budget)
    ).count()


########################################################################
########################################################################
#
def reassign_allocations(budget: Budget) -> int:
    """Reassign all TransactionAllocations from *budget* to unallocated.

    For each Transaction that has an allocation pointing to *budget*,
    calls transaction_svc.split() with a splits dict that omits *budget*.
    split() automatically routes the freed portion to the account's
    unallocated budget and updates all budget_balance snapshots.

    Args:
        budget: The budget whose allocations should be reassigned.

    Returns:
        Total number of allocation rows moved to unallocated.
    """
    tx_ids = list(
        TransactionAllocation.objects.filter(budget=budget)
        .values_list("transaction_id", flat=True)
        .distinct()
    )
    if not tx_ids:
        return 0

    transactions = list(Transaction.objects.filter(id__in=tx_ids))
    total_reassigned = 0

    for tx in transactions:
        allocs = list(
            TransactionAllocation.objects.filter(transaction=tx).select_related(
                "budget"
            )
        )

        splits: dict[str, Decimal] = {}
        removed = 0
        for a in allocs:
            if a.budget is not None and str(a.budget.id) != str(budget.id):
                splits[str(a.budget.id)] = abs(a.amount.amount)
            else:
                removed += 1

        transaction_svc.split(tx, splits)
        total_reassigned += removed

    return total_reassigned


########################################################################
########################################################################
#
def reverse_internal_transactions(budget: Budget) -> int:
    """Reverse (and delete) all InternalTransactions that involve *budget*.

    Each ITX where *budget* is src or dst is reversed through
    internal_transaction_svc.delete(), which restores both sides'
    balances before removing the row.  ITXs are reversed in reverse
    chronological order so the most recent effects are undone first.

    NOTE: The model docstring warns that bulk-deletion of
    InternalTransactions bypasses balance accounting.  This function
    deliberately reverses them one-by-one through the service layer.

    Args:
        budget: The budget whose InternalTransactions should be reversed.

    Returns:
        Number of InternalTransaction rows reversed.
    """
    itxs = list(
        InternalTransaction.objects.filter(
            Q(src_budget=budget) | Q(dst_budget=budget)
        )
        .select_related("src_budget", "dst_budget")
        .order_by("-created_at")
    )

    for itx in itxs:
        internal_transaction_svc.delete(itx)

    return len(itxs)


########################################################################
########################################################################
#
def system_user() -> User:
    """Return the non-loginable funding-system user.

    Uses users.models.User directly because AUTH_USER_MODEL is
    users.models.User in this project.

    Returns:
        The User instance with username FUNDING_SYSTEM_USERNAME.

    Raises:
        CommandError: If the data migration has not been run.
    """
    try:
        return User.objects.get(username=settings.FUNDING_SYSTEM_USERNAME)
    except User.DoesNotExist as exc:
        raise CommandError(
            f"System user '{settings.FUNDING_SYSTEM_USERNAME}' not found. "
            "Run migrations first."
        ) from exc
