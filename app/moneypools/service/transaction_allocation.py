"""
TransactionAllocation service -- Phase 3.

Operations:
    create(transaction, budget, amount, **kwargs)
        Credits budget.balance, saves the allocation, recalculates
        running budget_balance snapshots from this transaction forward.

    update_amount(allocation, new_amount)
        Adjusts budget.balance by the delta, saves the allocation,
        recalculates running budget_balance snapshots from this
        transaction forward.

    delete(allocation)
        Debits budget.balance, deletes the allocation, recalculates
        running budget_balance snapshots from the deleted allocation's
        transaction forward.

Convention: these primitives are not called by views directly.
TransactionService.split() (Phase 4) composes them.  During the
Phase 3 → 4 transition, TransactionViewSet.splits/perform_create
call them directly.
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
from django.db.models import Q, Sum

from moneypools.models import (
    Budget,
    InternalTransaction,
    Transaction,
    TransactionAllocation,
)


########################################################################
########################################################################
#
def create(
    transaction: Transaction,
    budget: Budget | None,
    amount: moneyed.Money,
    **kwargs: Any,
) -> TransactionAllocation:
    """Create an allocation, credit budget.balance, and recalculate snapshots.

    Args:
        transaction: The transaction this allocation belongs to.
        budget: The budget to credit.  If None, defaults to the
            transaction's bank account's unallocated budget.
        amount: Signed amount (negative for debits, positive for credits).
        **kwargs: Additional TransactionAllocation field values (category,
            memo, etc.).

    Returns:
        The saved TransactionAllocation instance.
    """
    if budget is None:
        budget = transaction.bank_account.unallocated_budget
    if budget is None:
        raise ValueError(
            "No budget specified and account has no unallocated budget."
        )
    with acquire_lock(budget.lock_key):
        with db_transaction.atomic():
            budget.refresh_from_db()
            budget.balance += amount
            allocation = TransactionAllocation(
                transaction=transaction,
                budget=budget,
                amount=amount,  # type: ignore[misc]
                **kwargs,
            )
            allocation.save()
            budget.save()
            _recalculate_running_balances(budget, transaction)
    return allocation


########################################################################
########################################################################
#
def update_amount(
    allocation: TransactionAllocation,
    new_amount: moneyed.Money,
) -> TransactionAllocation:
    """Update an allocation's amount, adjusting budget.balance by the delta.

    Args:
        allocation: The TransactionAllocation to update.
        new_amount: The new signed amount.

    Returns:
        The updated TransactionAllocation instance (refreshed from DB).
    """
    budget = allocation.budget
    if budget is None:
        raise ValueError(
            "Cannot update an allocation whose budget has been nulled."
        )
    transaction = allocation.transaction
    with acquire_lock(budget.lock_key):
        with db_transaction.atomic():
            allocation.refresh_from_db()
            budget.refresh_from_db()
            budget.balance = budget.balance - allocation.amount + new_amount
            allocation.amount = new_amount
            allocation.save()
            budget.save()
            _recalculate_running_balances(budget, transaction)
    allocation.refresh_from_db()
    return allocation


########################################################################
########################################################################
#
def delete(allocation: TransactionAllocation) -> None:
    """Delete an allocation, reversing its effect on budget.balance.

    Args:
        allocation: The TransactionAllocation to delete.

    Raises:
        ValueError: If the allocation has no budget (FK was nulled by
            a Transaction or Budget deletion).
    """
    budget = allocation.budget
    if budget is None:
        raise ValueError(
            "Cannot delete an allocation whose budget has been nulled."
        )
    transaction = allocation.transaction
    with acquire_lock(budget.lock_key):
        with db_transaction.atomic():
            budget.refresh_from_db()
            allocation.refresh_from_db()
            budget.balance -= allocation.amount
            budget.save()
            allocation.delete()
            _recalculate_running_balances(budget, transaction)


########################################################################
########################################################################
#
def _money_amount(value: Any) -> Decimal:
    """Extract a plain Decimal from a Money or Decimal value."""
    return value.amount if hasattr(value, "amount") else value


########################################################################
########################################################################
#
def _internal_transaction_delta(
    budget: Budget,
    after: datetime,
    before: datetime,
) -> Decimal:
    """Sum the net InternalTransaction effect on budget in (after, before].

    Uses effective_date as the event timestamp so that backfill-supplied
    economic datetimes take precedence over the physical row-creation time.

    Args:
        budget: The budget to check.
        after: Exclusive lower bound (transaction_date of prior allocation).
        before: Inclusive upper bound (transaction_date of current allocation).

    Returns:
        Net balance change from InternalTransactions in the window.
    """
    window = Q(effective_date__gt=after, effective_date__lte=before)
    credits = InternalTransaction.objects.filter(dst_budget=budget).filter(
        window
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    debits = InternalTransaction.objects.filter(src_budget=budget).filter(
        window
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    return Decimal(credits) - Decimal(debits)


########################################################################
########################################################################
#
def recalculate_from_dt(budget: Budget, from_dt: datetime) -> None:
    """Trigger a running-balance recalculation starting from the first
    allocation at or after from_dt.

    Called by the InternalTransaction service after an ITx is created or
    deleted, so that the allocation snapshots for both affected budgets
    stay in sync with the new funding state.

    Args:
        budget: The budget whose snapshots need updating.
        from_dt: Recalculate from the first allocation whose
            transaction_date is >= this datetime.
    """
    first = (
        TransactionAllocation.objects.filter(budget=budget)
        .filter(transaction__transaction_date__gte=from_dt)
        .order_by(
            "transaction__transaction_date",
            "transaction__created_at",
            "created_at",
        )
        .select_related("transaction")
        .first()
    )
    if first is not None:
        _recalculate_running_balances(budget, first.transaction)


########################################################################
########################################################################
#
def recalculate_itx_snapshots_from_dt(
    budget: Budget, from_dt: datetime
) -> None:
    """Recalculate src/dst_budget_balance snapshots on InternalTransaction rows.

    Walk all InternalTransactions involving budget at or after from_dt
    (ordered by effective_date, created_at) and update the balance snapshot
    field so it reflects the budget's actual balance after that transfer.

    Must be called after recalculate_from_dt so that TransactionAllocation
    budget_balance snapshots are fresh and can be used as anchors.

    Args:
        budget: The budget whose ITx snapshots need updating.
        from_dt: Recalculate ITxs with effective_date >= this datetime.
    """
    itxs = list(
        InternalTransaction.objects.filter(
            Q(src_budget=budget) | Q(dst_budget=budget),
            effective_date__gte=from_dt,
        ).order_by("effective_date", "created_at")
    )
    if not itxs:
        return

    # Anchor: last allocation strictly before from_dt.  By definition there
    # are no allocations between this anchor and from_dt.
    prior_alloc = (
        TransactionAllocation.objects.filter(budget=budget)
        .filter(transaction__transaction_date__lt=from_dt)
        .order_by(
            "-transaction__transaction_date",
            "-transaction__created_at",
            "-created_at",
        )
        .select_related("transaction")
        .first()
    )

    if prior_alloc is not None:
        running = _money_amount(prior_alloc.budget_balance)
        anchor_dt = prior_alloc.transaction.transaction_date
    else:
        total_allocs = TransactionAllocation.objects.filter(
            budget=budget
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        total_credits = InternalTransaction.objects.filter(
            dst_budget=budget
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        total_debits = InternalTransaction.objects.filter(
            src_budget=budget
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        running = (
            budget.balance.amount
            - Decimal(total_allocs)
            - Decimal(total_credits)
            + Decimal(total_debits)
        )
        anchor_dt = datetime.min.replace(tzinfo=UTC)

    # Add net ITx effects strictly between anchor_dt and from_dt.
    credits_between = InternalTransaction.objects.filter(
        dst_budget=budget,
        effective_date__gt=anchor_dt,
        effective_date__lt=from_dt,
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    debits_between = InternalTransaction.objects.filter(
        src_budget=budget,
        effective_date__gt=anchor_dt,
        effective_date__lt=from_dt,
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    running += Decimal(credits_between) - Decimal(debits_between)

    # Walk forward, maintaining the running balance.  At each ITx, running
    # is the budget balance just before the transfer fires.
    prev_effective_date = from_dt
    for itx in itxs:
        # Allocs at effective_date T come after all ITxs at T, so the window
        # of allocations between consecutive ITxs is [prev, itx.effective_date).
        if prev_effective_date < itx.effective_date:
            alloc_delta = TransactionAllocation.objects.filter(
                budget=budget,
                transaction__transaction_date__gte=prev_effective_date,
                transaction__transaction_date__lt=itx.effective_date,
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
            running += Decimal(alloc_delta)

        # src_budget FK uses to_field="id" so src_budget_id is a UUID.
        if itx.src_budget_id == budget.id:
            new_snapshot = running - _money_amount(itx.amount)
            if _money_amount(itx.src_budget_balance) != new_snapshot:
                InternalTransaction.objects.filter(pk=itx.pk).update(
                    src_budget_balance=new_snapshot
                )
        else:
            new_snapshot = running + _money_amount(itx.amount)
            if _money_amount(itx.dst_budget_balance) != new_snapshot:
                InternalTransaction.objects.filter(pk=itx.pk).update(
                    dst_budget_balance=new_snapshot
                )
        running = new_snapshot
        prev_effective_date = itx.effective_date


########################################################################
########################################################################
#
def _recalculate_running_balances(
    budget: Budget,
    from_transaction: Transaction,
) -> None:
    """Recalculate budget_balance snapshots from a chronological point forward.

    Only updates allocations at or after from_transaction's position.
    Between consecutive allocations, accounts for any InternalTransactions
    that changed the budget balance.

    Ordering: transaction_date, then transaction.created_at for ties.

    Window boundaries use transaction.transaction_date (a datetime) rather
    than allocation.created_at.  This prevents the same InternalTransaction
    from being captured multiple times when allocations are added
    out-of-chronological-session order.

    Args:
        budget: The budget whose allocations need recalculation.
        from_transaction: The transaction at which to start.
    """
    tx_date = from_transaction.transaction_date
    tx_created = from_transaction.created_at

    chronological = (
        "transaction__transaction_date",
        "transaction__created_at",
        "created_at",
    )

    prior = (
        TransactionAllocation.objects.filter(budget=budget)
        .filter(
            Q(transaction__transaction_date__lt=tx_date)
            | Q(
                transaction__transaction_date=tx_date,
                transaction__created_at__lt=tx_created,
            )
        )
        .order_by(
            "-transaction__transaction_date",
            "-transaction__created_at",
            "-created_at",
        )
        .select_related("transaction")
        .first()
    )

    if prior is not None:
        running = _money_amount(prior.budget_balance)
        prev_dt = prior.transaction.transaction_date
    else:
        # Baseline: budget's current balance minus all allocation amounts
        # and all InternalTransaction net effects.
        total_allocs = TransactionAllocation.objects.filter(
            budget=budget
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        total_credits = InternalTransaction.objects.filter(
            dst_budget=budget
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        total_debits = InternalTransaction.objects.filter(
            src_budget=budget
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        running = (
            budget.balance.amount
            - Decimal(total_allocs)
            - Decimal(total_credits)
            + Decimal(total_debits)
        )
        prev_dt = datetime.min.replace(tzinfo=UTC)

    forward = (
        TransactionAllocation.objects.filter(budget=budget)
        .filter(
            Q(transaction__transaction_date__gt=tx_date)
            | Q(
                transaction__transaction_date=tx_date,
                transaction__created_at__gte=tx_created,
            )
        )
        .order_by(*chronological)
        .select_related("transaction")
    )

    for alloc in forward:
        running += _internal_transaction_delta(
            budget, after=prev_dt, before=alloc.transaction.transaction_date
        )
        running += _money_amount(alloc.amount)
        current = _money_amount(alloc.budget_balance)
        if current != running:
            TransactionAllocation.objects.filter(pk=alloc.pk).update(
                budget_balance=running
            )
        prev_dt = alloc.transaction.transaction_date
