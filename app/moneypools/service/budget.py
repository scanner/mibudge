"""
Budget service -- Phase 2.

Operations:
    create(bank_account, name, budget_type, ...)
        Saves the budget and creates the fill-up goal child when
        with_fillup_goal=True (logic moved from budget_post_save signal).

    update(budget, **changes)
        Saves mutable fields under a budget lock.  Creates the fill-up
        goal child when with_fillup_goal flips to True on an existing
        budget that has none yet.

    archive(budget, actor)
        Drains fill-up balance first (if any), then this budget's
        balance, both via InternalTransactionService, then marks both
        archived -- all inside one atomic block.

    delete(budget, actor)
        Guards against unallocated or allocation-bearing budgets, drains
        remaining balance to/from unallocated (handles negative balance),
        nulls the fillup_goal FK, cascade-deletes the fill-up child, then
        deletes this budget -- all under sorted budget locks.
"""

# system imports
#
from contextlib import ExitStack
from typing import Any

# Project imports
#
from common.locks import acquire_lock

# 3rd party imports
#
from django.db import transaction as db_transaction
from djmoney.money import Money

from moneypools.models import BankAccount, Budget
from moneypools.service import internal_transaction as internal_transaction_svc
from users.models import User


########################################################################
########################################################################
#
def create(
    bank_account: BankAccount,
    name: str,
    budget_type: str,
    funding_type: str,
    target_balance: Money,
    **kwargs: Any,
) -> Budget:
    """Create a budget and optionally its fill-up goal child.

    Saves the budget (which fires budget_pre_save for currency alignment
    and complete-flag management).  If the new budget is RECURRING with
    with_fillup_goal=True an ASSOCIATED_FILLUP_GOAL child is created and
    linked back via fillup_goal.

    Args:
        bank_account: The bank account this budget belongs to.
        name: Human-readable budget name.
        budget_type: One of Budget.BudgetType values.
        funding_type: One of Budget.FundingType values.
        target_balance: Target funding amount.
        **kwargs: Any other Budget field values (paused, target_date,
            funding_amount, funding_schedule, recurrance_schedule, memo,
            with_fillup_goal, etc.).

    Returns:
        The saved Budget instance (with fillup_goal set if applicable).
    """
    budget = Budget(
        bank_account=bank_account,
        name=name,
        budget_type=budget_type,
        funding_type=funding_type,
        target_balance=target_balance,  # type: ignore[misc]
        **kwargs,
    )
    budget.save()
    _maybe_create_fillup(budget)
    return budget


########################################################################
########################################################################
#
def update(budget: Budget, **changes: Any) -> Budget:
    """Update mutable fields on an existing budget.

    Acquires the budget lock, applies *changes*, saves, then creates the
    fill-up goal child if with_fillup_goal has just been enabled.

    If the budget is RECURRING with an existing fill-up goal, any change to
    target_balance, funding_schedule, or name is mirrored onto the fill-up
    goal (those fields are copied from the parent at creation time and must
    stay in sync).  The fill-up goal's lock is also acquired in that case.

    Args:
        budget: The Budget instance to update.
        **changes: Field-value pairs to apply.  Only supply the fields
            being changed.

    Returns:
        The updated Budget instance (refreshed from DB).
    """
    fillup: Budget | None = None
    if (
        budget.budget_type == Budget.BudgetType.RECURRING
        and budget.with_fillup_goal
        and budget.fillup_goal_id is not None
        and _FILLUP_SYNCED_FIELDS & changes.keys()
    ):
        fillup = Budget.objects.get(id=budget.fillup_goal_id)

    with ExitStack() as stack:
        stack.enter_context(acquire_lock(budget.lock_key))
        if fillup is not None:
            stack.enter_context(acquire_lock(fillup.lock_key))

        with db_transaction.atomic():
            for field, value in changes.items():
                setattr(budget, field, value)
            budget.save()
            _maybe_create_fillup(budget)
            if fillup is not None:
                _sync_fillup(budget, fillup, changes)

    budget.refresh_from_db()
    return budget


########################################################################
########################################################################
#
def archive(budget: Budget, actor: User) -> Budget:
    """Archive a budget, draining its balance (and fill-up's) to unallocated.

    Sequence (all inside one atomic block):
        1. If a fill-up goal exists and has a positive balance, transfer
           it to unallocated via InternalTransactionService, then mark
           the fill-up archived.
        2. Re-fetch this budget and transfer its positive balance (if
           any) to unallocated via InternalTransactionService.
        3. Mark this budget archived.

    Args:
        budget: The Budget to archive.  Must not be the account's
            unallocated budget and must not already be archived.
        actor: The user performing the archive.

    Returns:
        The archived Budget instance (refreshed from DB).

    Raises:
        ValueError: If budget is the unallocated budget or is already
            archived.
        ValueError: If no unallocated budget is found on the account.
    """
    if budget.bank_account.unallocated_budget_id == budget.id:
        raise ValueError("Cannot archive the unallocated budget.")
    if budget.archived:
        raise ValueError("Budget is already archived.")

    unallocated = budget.bank_account.unallocated_budget
    if unallocated is None:
        raise ValueError("No unallocated budget found for this account.")

    with db_transaction.atomic():
        if budget.fillup_goal_id:
            fillup = Budget.objects.get(id=budget.fillup_goal_id)
            if fillup.balance.amount > 0:
                internal_transaction_svc.create(
                    bank_account=budget.bank_account,
                    src_budget=fillup,
                    dst_budget=unallocated,
                    amount=fillup.balance,
                    actor=actor,
                )
            fillup.refresh_from_db()
            fillup.archived = True
            fillup.save()

        budget.refresh_from_db()
        if budget.balance.amount > 0:
            internal_transaction_svc.create(
                bank_account=budget.bank_account,
                src_budget=budget,
                dst_budget=unallocated,
                amount=budget.balance,
                actor=actor,
            )

        budget.refresh_from_db()
        budget.archived = True
        budget.save()

    budget.refresh_from_db()
    return budget


########################################################################
########################################################################
#
def delete(budget: Budget, actor: User) -> None:
    """Delete a budget, draining its balance to (or from) unallocated first.

    Guards:
        - Raises ValueError if budget is the account's unallocated budget.
        - Raises ValueError if the budget has transaction allocations
          (caller should archive instead).

    Balance handling (under sorted budget + unallocated locks):
        - Positive balance: transferred to unallocated by direct balance
          mutation (no InternalTransaction record; the budget is gone).
        - Negative balance: unallocated absorbs the deficit (unallocated
          is debited by the absolute amount).
        - Zero balance: no transfer.

    The fill-up goal child (if any) is also deleted.

    Args:
        budget: The Budget instance to delete.
        actor: The user performing the deletion (reserved for future
            audit logging).

    Raises:
        ValueError: If budget is the unallocated budget.
        ValueError: If budget has transaction allocations.
    """
    if budget.bank_account.unallocated_budget_id == budget.id:
        raise ValueError("Cannot delete the unallocated budget.")
    if budget.transaction_allocations.exists():
        raise ValueError(
            "Cannot delete a budget that has transaction allocations. "
            "Archive it instead."
        )

    unallocated = budget.bank_account.unallocated_budget
    if unallocated is None:
        raise ValueError("No unallocated budget found for this account.")

    budgets_to_lock = sorted([budget, unallocated], key=lambda b: str(b.id))
    with ExitStack() as stack:
        for b in budgets_to_lock:
            stack.enter_context(acquire_lock(b.lock_key))

        with db_transaction.atomic():
            budget.refresh_from_db()
            unallocated.refresh_from_db()

            amount = budget.balance.amount
            if amount > 0:
                # Move surplus to unallocated.
                unallocated.balance += budget.balance
                budget.balance -= budget.balance
                unallocated.save()
            elif amount < 0:
                # Budget owes money; unallocated absorbs the deficit.
                unallocated.balance += budget.balance  # adds a negative
                budget.balance -= budget.balance  # zero out
                unallocated.save()

            # Null out the fillup FK so SET_NULL doesn't issue a spurious
            # UPDATE on the row we're about to delete, then delete the
            # fill-up child.
            if budget.fillup_goal_id:
                fillup_id = budget.fillup_goal_id
                Budget.objects.filter(id=budget.id).update(fillup_goal_id=None)
                budget.fillup_goal_id = None
                Budget.objects.filter(id=fillup_id).delete()

            budget.delete()


# Fields on a recurring budget that must be mirrored onto its fill-up goal.
_FILLUP_SYNCED_FIELDS: frozenset[str] = frozenset(
    {"target_balance", "funding_schedule", "name"}
)


########################################################################
########################################################################
#
def _sync_fillup(
    budget: Budget,
    fillup: Budget,
    changes: dict[str, Any],
) -> None:
    """Mirror synced fields from *budget* onto its fill-up goal.

    Called inside update() when any of _FILLUP_SYNCED_FIELDS are changing.
    The fill-up goal's name is kept as '{budget.name} Fill-up'.

    Args:
        budget: The parent recurring budget (already saved with new values).
        fillup: The associated fill-up goal to update.
        changes: The changes dict passed to update().
    """
    dirty = False
    if "target_balance" in changes:
        fillup.target_balance = budget.target_balance
        dirty = True
    if "funding_schedule" in changes:
        fillup.funding_schedule = budget.funding_schedule
        dirty = True
    if "name" in changes:
        fillup.name = f"{budget.name} Fill-up"
        dirty = True
    if dirty:
        fillup.save()


########################################################################
########################################################################
#
def _maybe_create_fillup(budget: Budget) -> None:
    """Create the fill-up goal child if the budget calls for one.

    Mirrors the logic previously in budget_post_save: only fires when
    budget_type is RECURRING, with_fillup_goal is True, and fillup_goal
    is not yet set.

    Uses queryset .update() to back-link fillup_goal_id without
    triggering another save signal on the parent.

    Args:
        budget: The Budget instance to inspect and potentially link.
    """
    if not (
        budget.budget_type == Budget.BudgetType.RECURRING
        and budget.with_fillup_goal
        and budget.fillup_goal_id is None
    ):
        return

    fillup = Budget(
        name=f"{budget.name} Fill-up",
        bank_account=budget.bank_account,
        budget_type=Budget.BudgetType.ASSOCIATED_FILLUP_GOAL,
        funding_schedule=budget.funding_schedule,
        target_balance=budget.target_balance,
    )
    fillup.save()
    Budget.objects.filter(id=budget.id).update(fillup_goal_id=fillup.id)
    budget.fillup_goal = fillup
