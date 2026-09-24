"""
Budget service -- Phase 2.

Operations:
    create(bank_account, name, budget_type, ...)
        Saves the budget and auto-creates the fill-up goal child for
        RECURRING budgets (logic moved from budget_post_save signal).

    update(budget, **changes)
        Saves mutable fields under a budget lock.  Creates the fill-up
        goal child if the budget is RECURRING and has none yet.
        On pause->unpause flip, resets both pointer fields to today-1
        and emits a warning per missed recur boundary (Recurring only).
        Returns (budget, warnings) -- warnings is empty on normal updates.

    archive(budget, actor)
        Drains fill-up balance first (if any), then this budget's
        balance, both via InternalTransactionService, then marks both
        archived -- all inside one atomic block.

    delete(budget, actor)
        Guards against unallocated or allocation-bearing budgets (the
        budget or its fill-up), reverses transfers with other budgets,
        drains the remaining balance of the budget and its fill-up
        to/from unallocated (handles negative balance), deletes both,
        and recalculates the snapshots of every budget whose transfer
        history was cascaded -- all under sorted budget locks.
"""

# system imports
#
import logging
from contextlib import ExitStack
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

# 3rd party imports
#
from django.db import transaction as db_transaction
from django.db.models import Q
from djmoney.money import Money

# Project imports
#
from common.locks import acquire_lock
from moneypools.models import BankAccount, Budget, InternalTransaction
from moneypools.service import internal_transaction as internal_transaction_svc
from moneypools.service import transaction_allocation as alloc_svc
from moneypools.service._locking import locked_many
from moneypools.service.schedules import (
    enumerate_schedule,
    normalize_dtstart,
    rules_fingerprint,
)
from moneypools.service.shared import funding_system_user
from users.models import User

logger = logging.getLogger(__name__)

# Recalculating from here rebuilds a budget's whole snapshot chain.
_EPOCH = datetime.min.replace(tzinfo=UTC)


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
    """Create a budget and auto-create its fill-up goal child if RECURRING.

    Saves the budget (which fires budget_pre_save for currency alignment
    and complete-flag management).  If the new budget is RECURRING an
    ASSOCIATED_FILLUP_GOAL child is created and linked back via fillup_goal.

    Args:
        bank_account: The bank account this budget belongs to.
        name: Human-readable budget name.
        budget_type: One of Budget.BudgetType values.
        funding_type: One of Budget.FundingType values.
        target_balance: Target funding amount.
        **kwargs: Any other Budget field values (paused, target_date,
            funding_amount, funding_schedule, recurrence_schedule, memo,
            etc.).

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

    # Set pointers to created_at.date() - 1 so the first scheduled event
    # fires on its scheduled date rather than being treated as already-seen.
    yesterday = budget.created_at.date() - timedelta(days=1)
    Budget.objects.filter(pk=budget.pk).update(
        last_funded_on=yesterday,
        last_recurrence_on=yesterday,
    )
    budget.last_funded_on = yesterday
    budget.last_recurrence_on = yesterday

    _maybe_create_fillup(budget)
    return budget


########################################################################
########################################################################
#
def update(budget: Budget, **changes: Any) -> tuple[Budget, list[str]]:
    """Update mutable fields on an existing budget.

    Acquires the budget lock, applies *changes*, saves, then creates the
    fill-up goal child if the budget is RECURRING and lacks one.

    If the budget is RECURRING with an existing fill-up goal, any change to
    target_balance, funding_schedule, or name is mirrored onto the fill-up
    goal (those fields are copied from the parent at creation time and must
    stay in sync).  The fill-up goal's lock is also acquired in that case.

    Pause-unpause pointer reset: when 'paused' flips from True to False,
    both last_funded_on and last_recurrence_on are reset to today-1.  This
    drops any events that fell during the pause window without replaying
    them.  For Recurring budgets, one warning is emitted per missed recur
    boundary so the caller can surface these to the user.

    Args:
        budget: The Budget instance to update.
        **changes: Field-value pairs to apply.  Only supply the fields
            being changed.

    Returns:
        A tuple of (updated Budget instance, list of warning strings).
        The warnings list is empty on normal (non-unpause) updates.
    """
    warnings: list[str] = []

    _reanchor_funding_schedule(budget, changes)

    # Detect pause->unpause before applying changes.
    was_paused = budget.paused
    unpausing = was_paused and changes.get("paused") is False

    if unpausing:
        yesterday = date.today() - timedelta(days=1)
        changes["last_funded_on"] = yesterday
        changes["last_recurrence_on"] = yesterday

        if (
            budget.budget_type == Budget.BudgetType.RECURRING
            and budget.recurrence_schedule
        ):
            old_pointer = budget.last_recurrence_on or (
                budget.created_at.date() - timedelta(days=1)
            )
            for boundary in enumerate_schedule(
                budget.recurrence_schedule, old_pointer, yesterday
            ):
                msg = (
                    f"Recurring '{budget.name}' was paused across recur"
                    f" boundary {boundary}; cycle skipped."
                )
                warnings.append(msg)
                logger.warning(msg)

    fillup: Budget | None = None
    if (
        budget.budget_type == Budget.BudgetType.RECURRING
        and budget.fillup_goal_id is not None
        and _FILLUP_SYNCED_FIELDS & changes.keys()
    ):
        fillup = Budget.objects.get(id=budget.fillup_goal_id)

    budgets_to_lock = [budget] if fillup is None else [budget, fillup]
    with ExitStack() as stack:
        for b in sorted(budgets_to_lock, key=lambda b: str(b.id)):
            stack.enter_context(acquire_lock(b.lock_key))

        with db_transaction.atomic():
            # `save()` writes every column, balance included, so the row
            # is re-read under lock before the changes are applied.
            #
            locked_many(budgets_to_lock)
            for field, value in changes.items():
                setattr(budget, field, value)
            budget.save()
            _maybe_create_fillup(budget)
            if fillup is not None:
                _sync_fillup(budget, fillup, changes)

    budget.refresh_from_db()
    return budget, warnings


########################################################################
########################################################################
#
def archive(budget: Budget, actor: User) -> Budget:
    """Archive a budget, draining its balance (and fill-up's) to unallocated.

    Sequence (all inside one atomic block, holding the Redis and row
    locks of this budget, its fill-up and the Unallocated budget):
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

    fillup: Budget | None = None
    if budget.fillup_goal_id:
        fillup = Budget.objects.get(id=budget.fillup_goal_id)
    budgets_to_lock = [budget, unallocated]
    if fillup is not None:
        budgets_to_lock.append(fillup)

    # The drain amounts are read under the row locks, and the nested
    # internal_transaction_svc.create calls re-enter the Redis locks
    # taken here.
    #
    with ExitStack() as stack:
        for b in sorted(budgets_to_lock, key=lambda b: str(b.id)):
            stack.enter_context(acquire_lock(b.lock_key))
        with db_transaction.atomic():
            locked_many(budgets_to_lock)

            if fillup is not None:
                if fillup.balance.amount > 0:
                    # Fill-up is a system-internal construct; attribute
                    # its sweep to the funding-system user, not the
                    # archiving user.
                    #
                    internal_transaction_svc.create(
                        bank_account=budget.bank_account,
                        src_budget=fillup,
                        dst_budget=unallocated,
                        amount=fillup.balance,
                        actor=funding_system_user(),
                        system_event_kind=None,
                        system_event_date=None,
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
    """Delete a budget and its fill-up goal, keeping the ledger balanced.

    Guards:
        - Raises ValueError if budget is the account's unallocated budget.
        - Raises ValueError if the budget or its fill-up goal has
          transaction allocations (caller should archive instead).

    Deleting a budget cascades away every InternalTransaction that
    touches it or its fill-up.  Under the Redis and row locks of the
    deleted budgets, Unallocated and every other budget those transfers
    touched:

        1. Each transfer between a deleted budget and another budget is
           reversed on the other budget (balance and, for Goals,
           funded_amount), as `internal_transaction_svc.delete` would.
        2. Whatever balance the deleted budgets still hold moves to
           Unallocated: a positive balance adds to it, a negative one
           is absorbed by it.  No InternalTransaction records this; the
           budgets are gone.
        3. The fill-up child and then the budget are deleted.
        4. Every other budget whose transfer history was cascaded has
           its running-balance snapshots recalculated from the earliest
           cascaded transfer.

    Args:
        budget: The Budget instance to delete.
        actor: The user performing the deletion (reserved for future
            audit logging).

    Raises:
        ValueError: If budget is the unallocated budget.
        ValueError: If budget or its fill-up goal has transaction
            allocations.
    """
    if budget.bank_account.unallocated_budget_id == budget.id:
        raise ValueError("Cannot delete the unallocated budget.")

    unallocated_id = budget.bank_account.unallocated_budget_id
    if unallocated_id is None:
        raise ValueError("No unallocated budget found for this account.")

    doomed = [budget]
    if budget.fillup_goal_id:
        doomed.append(Budget.objects.get(id=budget.fillup_goal_id))
    _raise_if_allocated(doomed)
    doomed_ids = {b.id for b in doomed}

    # The counterparties must be known before their locks are taken, and
    # locks go in `id` order.  An InternalTransaction touching a deleted
    # budget needs that budget's Redis lock, so once the locks are held
    # the set cannot grow; if it grew before they were taken, retry with
    # the larger set.
    #
    counterparty_ids = _itx_counterparty_ids(doomed_ids)
    while True:
        with ExitStack() as stack:
            others = {
                b.id: b
                for b in Budget.objects.filter(
                    id__in=counterparty_ids | {unallocated_id}
                )
            }
            to_lock = sorted(
                [*doomed, *others.values()], key=lambda b: str(b.id)
            )
            for b in to_lock:
                stack.enter_context(acquire_lock(b.lock_key))

            current_ids = _itx_counterparty_ids(doomed_ids)
            if not current_ids <= counterparty_ids:
                counterparty_ids |= current_ids
                continue

            with db_transaction.atomic():
                locked_many(to_lock)
                _delete_locked(budget, doomed, others, others[unallocated_id])
            return


########################################################################
########################################################################
#
def _raise_if_allocated(budgets: list[Budget]) -> None:
    """Raise ValueError if any of `budgets` has transaction allocations.

    Args:
        budgets: The budgets about to be deleted.

    Raises:
        ValueError: If any budget has a TransactionAllocation.
    """
    for b in budgets:
        if b.transaction_allocations.exists():
            raise ValueError(
                "Cannot delete a budget that has transaction allocations. "
                "Archive it instead."
            )


########################################################################
########################################################################
#
def _itx_counterparty_ids(budget_ids: set[UUID]) -> set[UUID]:
    """Return the ids of other budgets that share a transfer with `budget_ids`.

    Args:
        budget_ids: The ids of the budgets being deleted.

    Returns:
        The ids of budgets outside `budget_ids` that are the source or
        destination of an InternalTransaction with one of them.
    """
    touching = InternalTransaction.objects.filter(
        Q(src_budget_id__in=budget_ids) | Q(dst_budget_id__in=budget_ids)
    ).values_list("src_budget_id", "dst_budget_id")
    ids = {bid for pair in touching for bid in pair}
    return ids - budget_ids


########################################################################
########################################################################
#
def _delete_locked(
    budget: Budget,
    doomed: list[Budget],
    others: dict[UUID, Budget],
    unallocated: Budget,
) -> None:
    """Body of `delete`; runs inside `atomic()` with every lock held.

    Args:
        budget: The budget being deleted.
        doomed: `budget` and its fill-up goal (if any), refreshed under
            row locks.
        others: Unallocated and every counterparty budget, by id,
            refreshed under row locks.
        unallocated: The account's Unallocated budget (also in `others`).
    """
    _raise_if_allocated(doomed)
    doomed_by_id = {b.id: b for b in doomed}

    # 1. Reverse each transfer between a deleted budget and another
    #    budget, and note the earliest one per other budget.
    #
    earliest: dict[UUID, datetime] = {}
    for itx in InternalTransaction.objects.filter(
        Q(src_budget_id__in=doomed_by_id) | Q(dst_budget_id__in=doomed_by_id)
    ):
        src_doomed = itx.src_budget_id in doomed_by_id
        dst_doomed = itx.dst_budget_id in doomed_by_id
        if src_doomed and dst_doomed:
            continue
        if src_doomed:
            src, dst = (
                doomed_by_id[itx.src_budget_id],
                others[itx.dst_budget_id],
            )
            other = dst
        else:
            src, dst = (
                others[itx.src_budget_id],
                doomed_by_id[itx.dst_budget_id],
            )
            other = src
        src.balance += itx.amount
        dst.balance -= itx.amount
        if other.budget_type == Budget.BudgetType.GOAL:
            if other is src:
                other.funded_amount += itx.amount
            else:
                other.funded_amount -= itx.amount
        if other.id not in earliest or itx.effective_date < earliest[other.id]:
            earliest[other.id] = itx.effective_date

    # 2. Move the remaining balance to Unallocated.  A positive balance
    #    adds to it; a negative balance is absorbed by it.
    #
    residual = sum(
        (b.balance for b in doomed), Money(0, unallocated.balance.currency)
    )
    for b in doomed:
        if b.balance.amount != 0:
            unallocated.balance += b.balance
            b.balance -= b.balance
    for other in others.values():
        other.save()

    # 3. Null out the fillup FK so SET_NULL doesn't issue a spurious
    #    UPDATE on the row we're about to delete, then delete the
    #    fill-up child and the budget.  Their InternalTransactions go
    #    with them (on_delete=CASCADE).
    #
    if budget.fillup_goal_id:
        fillup_id = budget.fillup_goal_id
        Budget.objects.filter(id=budget.id).update(fillup_goal_id=None)
        budget.fillup_goal_id = None
        Budget.objects.filter(id=fillup_id).delete()
    budget.delete()

    # 4. Recalculate the snapshots of every budget whose history lost
    #    a transfer.  A residual moved into Unallocated has no event of
    #    its own, so Unallocated is then rebuilt from the start.
    #
    if residual.amount != 0:
        earliest[unallocated.id] = _EPOCH
    for other_id, from_dt in earliest.items():
        alloc_svc.recalculate_from_dt(others[other_id], from_dt)


# Fields on a recurring budget that must be mirrored onto its fill-up goal.
_FILLUP_SYNCED_FIELDS: frozenset[str] = frozenset(
    {"target_balance", "funding_schedule", "name"}
)


########################################################################
########################################################################
#
def _reanchor_funding_schedule(
    budget: Budget,
    changes: dict[str, Any],
) -> None:
    """Re-anchor or preserve the funding schedule's DTSTART on update.

    Mutates *changes* in place.  Policy: editing the funding dates (the
    schedule's recurrence pattern) or the goal date re-figures the
    schedule -- DTSTART moves to the first real occurrence on/after
    today, resetting the pace baseline.  An update that touches neither
    keeps the stored anchor, even though SPA clients always send the
    schedule back as a bare RRULE on full-object PUTs.

    When only the target date changes, the stored DTSTART is kept as the
    rule anchor so bare-FREQ rules (whose fire day comes from DTSTART)
    keep firing on the same day while the anchor moves forward.

    Args:
        budget: The Budget being updated (holds the stored schedule).
        changes: The update's field-value pairs; 'funding_schedule' is
            added or replaced as needed.
    """
    if "funding_schedule" not in changes and "target_date" not in changes:
        return

    incoming = changes.get("funding_schedule", budget.funding_schedule)
    if not incoming or not incoming.rrules:
        return

    stored = budget.funding_schedule
    rule_changed = "funding_schedule" in changes and rules_fingerprint(
        incoming
    ) != rules_fingerprint(stored)
    date_changed = (
        "target_date" in changes
        and changes["target_date"] != budget.target_date
    )

    if rule_changed or date_changed:
        if not rule_changed and stored and stored.dtstart is not None:
            # Same pattern, new goal date: keep the stored anchor as the
            # rule anchor; normalize_dtstart moves it forward from today.
            incoming.dtstart = stored.dtstart
        changes["funding_schedule"] = normalize_dtstart(incoming, date.today())
    elif incoming.dtstart is None:
        # Pattern and date unchanged; the client just echoed the stored
        # schedule without its anchor.  Preserve it -- or backfill from
        # the creation date for rows predating DTSTART anchoring.
        if stored is not None and stored.dtstart is not None:
            incoming.dtstart = stored.dtstart
            changes["funding_schedule"] = incoming
        else:
            changes["funding_schedule"] = normalize_dtstart(
                incoming, budget.created_at.date()
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

    Only fires when budget_type is RECURRING and fillup_goal is not yet set.

    Uses queryset .update() to back-link fillup_goal_id without
    triggering another save signal on the parent.

    Args:
        budget: The Budget instance to inspect and potentially link.
    """
    if not (
        budget.budget_type == Budget.BudgetType.RECURRING
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
