# system imports
#
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

# 3rd party imports
#
from django.db import transaction as db_transaction
from django.db.models import Q, Sum
from django.db.models.signals import (
    post_delete,
    post_save,
    pre_delete,
    pre_save,
)
from django.dispatch import receiver

# Project imports
#
from .models import (
    BankAccount,
    Budget,
    InternalTransaction,
    Transaction,
    TransactionAllocation,
)

# To make our logic simpler every bank account will always have an unallocated
# budget. This budget is created when the bank account is first saved. We do
# not allow the creation of any other budget associated with a bank account to
# have the same name. The user may not delete/archive this budget.
#
# When a Transaction is imported, the import service creates a default
# TransactionAllocation pointing at the unallocated budget.
#
# NOTE: Proposing a logic change: When you create a transaction, it
#       automatically gets a TransactionAllocation pointing at the unallocated
#       budget.
#
UNALLOCATED_BUDGET_NAME = "Unallocated"


####################################################################
#
@receiver(pre_save, sender=BankAccount)
def bank_account_pre_save(
    sender: type[BankAccount], instance: BankAccount, **kwargs: Any
) -> None:
    """Propagate currency settings when a bank account is created.

    On creation, if no currency is set, inherits the bank's
    default_currency.  Always aligns posted_balance and
    available_balance currencies with the account's currency.

    Args:
        sender: The BankAccount model class.
        instance: The BankAccount instance about to be saved.
        **kwargs: Additional signal keyword arguments.
    """
    bank_account = instance

    if bank_account.pkid is None:
        # Default to the bank's currency if the caller did not
        # specify one.
        #
        if not bank_account.currency:
            bank_account.currency = bank_account.bank.default_currency

        # Align balance currencies with the account currency.
        #
        bank_account.posted_balance_currency = bank_account.currency
        bank_account.available_balance_currency = bank_account.currency


####################################################################
#
@receiver(post_save, sender=BankAccount)
def bank_account_post_save(
    sender: type[BankAccount],
    instance: BankAccount,
    created: bool,
    **kwargs: Any,
) -> None:
    """Create the unallocated budget when a new bank account is saved.

    The unallocated budget is created in post_save (not pre_save)
    because it needs a saved BankAccount to reference via FK.  Its
    initial balance matches the account's available_balance.

    Args:
        sender: The BankAccount model class.
        instance: The BankAccount instance that was just saved.
        created: True if this is a new record.
        **kwargs: Additional signal keyword arguments.
    """
    bank_account = instance  # To make the code easier to read

    # Create and setup the unallocated budget if this bank account is being
    # created. We have to do this in the post_save signal because the budget
    # needs to be able to reference bank via a foreign key.
    #
    # NOTE: This is the first budget in the bank account and it gets set to the
    # bank account's available balance (ie: all the funds are put into this
    # first created budget)
    #
    if created:
        unallocated_budget = Budget(
            name="Unallocated",
            bank_account=bank_account,
            target_date=datetime.now(UTC).date(),
            balance=bank_account.available_balance,
        )
        unallocated_budget.save()
        bank_account.unallocated_budget = unallocated_budget
        BankAccount.objects.filter(id=bank_account.id).update(
            unallocated_budget_id=unallocated_budget.id
        )


####################################################################
#
@receiver(pre_save, sender=Budget)
def budget_pre_save(
    sender: type[Budget], instance: Budget, **kwargs: Any
) -> None:
    """Align currencies and manage the 'complete' flag before each save.

    Currency alignment:
        Sets balance_currency and target_balance_currency to match the
        bank account's currency on every save so balances stay aligned
        if a budget is saved after its bank account's currency was
        corrected.

    'complete' flag management:
        Goal (G) -- set True when balance >= target; never cleared here.
            Once a goal is funded it stays funded regardless of spending.

        Capped (C) -- set True when balance >= target; cleared when
            balance drops below target.  This produces the "perpetual
            top-up to a cap" behavior: spending from the budget
            automatically re-enables automatic funding.

        Recurring (R) -- 'complete' is set True when balance >= target
            here, but it is cleared by the recurrence task (cycle reset),
            not by balance changes.

        Unallocated / Associated fill-up (no target) -- left unchanged.

    Args:
        sender: The Budget model class.
        instance: The Budget instance about to be saved.
        **kwargs: Additional signal keyword arguments.
    """
    acct_currency = instance.bank_account.currency
    instance.balance_currency = acct_currency  # type: ignore[attr-defined]
    instance.target_balance_currency = acct_currency  # type: ignore[attr-defined]

    # Set archived_at the first time a budget is archived.
    if instance.archived and instance.archived_at is None:
        instance.archived_at = datetime.now(UTC)

    # Manage 'complete' for budget types with meaningful funding targets.
    # target_balance of 0 means "no cap set" -- skip those.
    #
    target = instance.target_balance.amount
    balance = instance.balance.amount

    if target > 0:
        match instance.budget_type:
            case Budget.BudgetType.GOAL | Budget.BudgetType.RECURRING:
                # Set when funded; never cleared here.
                # Goal: permanently done once funded.
                # Recurring: cleared by the recurrence task on cycle reset.
                if balance >= target:
                    instance.complete = True
            case Budget.BudgetType.CAPPED:
                # Always reflects whether the cap is currently met, so
                # spending from a capped budget immediately re-enables
                # automatic funding.
                instance.complete = balance >= target


####################################################################
#
@receiver(pre_save, sender=Transaction)
def transaction_pre_save(sender, instance, **kwargs):
    """
    Handle bank account balance updates when a transaction is saved.

    This signal handles ONLY bank account balances (available and posted).
    Budget balances are handled by TransactionAllocation signals.

    NOTE: Transactions can not change bank accounts.

    Keyword Arguments:
    sender    -- What sent the signal. In our case always Transaction
    instance  -- instance of Transaction object before save
    **kwargs  -- dict
    """
    transaction = instance  # To make the code easier to read

    # If the -editable- description is not set, then set it to a stripped
    # version of the raw description.
    #
    if not transaction.description:
        transaction.description = transaction.raw_description.strip()

    # If the pkid is None then this is a newly created Transaction that has not
    # yet been saved to the db. This part of the `if` clause deals with newly
    # created transactions.
    #
    if transaction.pkid is None:
        # Update the bank account's available & posted balance.
        #
        transaction.bank_account.available_balance += transaction.amount
        transaction.bank_account_available_balance = (
            transaction.bank_account.available_balance
        )
        # If this transaction is not pending, then also update the posted
        # amount for the bank account.
        #
        if not transaction.pending:
            transaction.bank_account.posted_balance += transaction.amount
        transaction.bank_account.save()

        # Whether we update the posted balance or not, save the current posted
        # balance in this transaction.
        #
        transaction.bank_account_posted_balance = (
            transaction.bank_account.posted_balance
        )
    else:
        # We only reach here if this transaction already exists and it is being
        # updated. So we need to compare in-memory transaction object with what
        # is already saved in the db to determine how to update related objects
        # and fields.
        #
        previous = Transaction.objects.get(id=transaction.id)

        # If the amount of the transaction has changed then we need to
        # change the bank account's available amount.
        #
        save_bank_account = False
        if previous.amount != transaction.amount:
            transaction.bank_account.available_balance -= previous.amount
            transaction.bank_account.available_balance += transaction.amount

            # If this transaction was previously posted then we need to change
            # the posted amount on the bank account as well.
            #
            # XXX This assumes that once a transaction is posted it never
            #     changes back to pending.
            #
            if not previous.pending:
                transaction.bank_account.posted_balance -= previous.amount
            if not transaction.pending:
                transaction.bank_account.posted_balance += transaction.amount

            save_bank_account = True

        elif not transaction.pending and previous.pending:
            # The transaction has changed from pending to posted so we need to
            # update the posted bank account balance.
            #
            transaction.bank_account.posted_balance += transaction.amount
            save_bank_account = True

        if save_bank_account:
            transaction.bank_account.save()


####################################################################
#
@receiver(post_save, sender=Transaction)
def transaction_post_save_link(
    sender: type[Transaction],
    instance: Transaction,
    created: bool,
    **kwargs: Any,
) -> None:
    """
    Enqueue the cross-account link attempt after a Transaction save.

    Only fires for newly created Transactions that are not already
    linked. The work runs in ``moneypools.tasks.attempt_link_transaction``
    so the request does not block on cross-account DB queries. The
    ``on_commit`` wrapper holds the dispatch until the surrounding
    transaction commits, which guarantees the Celery worker can read
    the row (and, importantly, that we do not enqueue work that gets
    rolled back on a later failure in the same request).

    Args:
        sender:   The Transaction model class.
        instance: The Transaction that was just saved.
        created:  True iff this is a new row.
        **kwargs: Additional signal keyword arguments.
    """
    if not created or instance.linked_transaction_id is not None:
        return

    # Import here rather than at module top to avoid the signals ->
    # tasks -> linking -> models import chain firing during app ready().
    #
    from moneypools.tasks import attempt_link_transaction

    transaction_id = str(instance.id)
    db_transaction.on_commit(
        lambda: attempt_link_transaction.delay(transaction_id)
    )


####################################################################
#
@receiver(pre_delete, sender=Transaction)
def transaction_pre_delete(sender, instance, **kwargs):
    """
    Reverse bank account balance changes when a transaction is deleted.

    Budget balance reversal is handled by the cascade delete of associated
    TransactionAllocation objects (via their own pre_delete signal).

    NOTE: bulk deleting transactions will NOT trigger this signal. Delete
    them one by one to keep balances correct.
    """
    transaction = instance  # To make the code easier to read

    # Update the bank account's available & posted balance.
    #
    if transaction.bank_account:
        transaction.bank_account.available_balance -= transaction.amount

        # If this transaction is not pending, then also update the posted
        # amount for the bank account.
        #
        if not transaction.pending:
            transaction.bank_account.posted_balance -= transaction.amount
        transaction.bank_account.save()


####################################################################
#
def _money_amount(value: Any) -> Decimal:
    """Extract a plain Decimal from a Money or Decimal value."""
    return value.amount if hasattr(value, "amount") else value


####################################################################
#
def _internal_transaction_delta(
    budget: Budget,
    after: datetime,
    before: datetime,
) -> Decimal:
    """Sum the net effect of InternalTransactions on *budget* whose
    ``created_at`` falls in the half-open interval ``(after, before]``.

    Credits (budget is ``dst_budget``) are positive, debits (budget is
    ``src_budget``) are negative.

    Args:
        budget: The budget to check.
        after:  Exclusive lower bound on ``created_at``.
        before: Inclusive upper bound on ``created_at``.

    Returns:
        Net balance change from InternalTransactions in the window.
    """
    window = Q(created_at__gt=after, created_at__lte=before)
    credits = InternalTransaction.objects.filter(dst_budget=budget).filter(
        window
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    debits = InternalTransaction.objects.filter(src_budget=budget).filter(
        window
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    return Decimal(credits) - Decimal(debits)


####################################################################
#
def _recalculate_running_balances(
    budget: Budget,
    from_transaction: Transaction,
) -> None:
    """Recalculate budget_balance snapshots from a chronological point
    forward.

    Only updates the allocation at the given transaction's position
    and any that follow it.  In the common case (allocation added at
    the end) this touches one row.

    Between consecutive allocations the walk also accounts for any
    InternalTransactions that changed the budget's balance (e.g.
    monthly top-ups from Unallocated).  These are detected by
    ``created_at`` falling between the two allocations' creation
    timestamps.

    Ordering: transaction_date, then transaction.created_at for ties.

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

    # The allocation immediately before the starting point gives us
    # the running balance to start from.
    #
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
        prev_created = prior.created_at
    else:
        # This is the chronologically first allocation.  Baseline is
        # the budget's current balance minus the sum of ALL its
        # allocation amounts AND all InternalTransaction effects.
        #
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
        prev_created = datetime.min.replace(tzinfo=UTC)

    # Walk forward, updating only rows whose snapshot is stale.
    # Between each pair of allocations, account for any
    # InternalTransactions that changed the budget balance.
    #
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
        # Add the net effect of any InternalTransactions created
        # between the previous allocation and this one.
        running += _internal_transaction_delta(
            budget, after=prev_created, before=alloc.created_at
        )

        running += _money_amount(alloc.amount)
        current = _money_amount(alloc.budget_balance)
        if current != running:
            TransactionAllocation.objects.filter(pk=alloc.pk).update(
                budget_balance=running
            )
        prev_created = alloc.created_at


####################################################################
#
@receiver(pre_save, sender=TransactionAllocation)
def allocation_pre_save(sender, instance, **kwargs):
    """
    Handle budget balance updates when an allocation is saved.

    On creation: credits the allocated amount to the budget.
    On update: if the budget changed, moves the amount between budgets.
              If the amount changed, adjusts the budget balance by the delta.

    Keyword Arguments:
    sender    -- What sent the signal. Always TransactionAllocation
    instance  -- instance of TransactionAllocation object before save
    **kwargs  -- dict
    """
    allocation = instance  # To make the code easier to read

    # If no budget is set, default to the transaction's bank account's
    # unallocated budget.
    #
    if allocation.budget is None:
        allocation.budget = (
            allocation.transaction.bank_account.unallocated_budget
        )

    # Stash for post_save so running balances can be recalculated
    # on both old and new budgets when a reassignment happens.
    #
    allocation._prev_budget = None

    if allocation.pkid is None:
        # New allocation: credit the budget by the allocation amount.
        #
        allocation.budget.balance += allocation.amount
        allocation.budget.save()
    else:
        # Existing allocation being updated.
        #
        previous = TransactionAllocation.objects.get(id=allocation.id)

        # If the budget changed, move the previous amount from old budget
        # to new budget.
        #
        if (
            previous.budget is not None
            and allocation.budget is not None
            and previous.budget != allocation.budget
        ):
            previous.budget.balance -= previous.amount
            previous.budget.save()
            allocation.budget.balance += previous.amount
            allocation.budget.save()
            allocation._prev_budget = previous.budget

        # If the amount changed, adjust the budget balance by the delta.
        #
        if previous.amount != allocation.amount:
            allocation.budget.balance -= previous.amount
            allocation.budget.balance += allocation.amount
            allocation.budget.save()


####################################################################
#
@receiver(post_save, sender=TransactionAllocation)
def allocation_post_save(sender, instance, **kwargs):
    """Recalculate running budget_balance snapshots after an
    allocation is created or updated.

    Only touches allocations at or after this transaction's
    chronological position.  If the budget was changed, both the
    old and new budget's running balances are recalculated.
    """
    allocation = instance
    tx = allocation.transaction

    if allocation.budget is not None:
        _recalculate_running_balances(allocation.budget, tx)

    prev = getattr(allocation, "_prev_budget", None)
    if prev is not None:
        _recalculate_running_balances(prev, tx)


####################################################################
#
@receiver(pre_delete, sender=TransactionAllocation)
def allocation_pre_delete(sender, instance, **kwargs):
    """
    Reverse budget balance changes when an allocation is deleted.

    NOTE: bulk deleting allocations will NOT trigger this signal. Delete
    them one by one to keep balances correct.
    """
    allocation = instance  # To make the code easier to read

    if allocation.budget is not None:
        allocation.budget.balance -= allocation.amount
        allocation.budget.save()

    # Stash for post_delete recalculation.
    allocation._delete_budget = allocation.budget
    allocation._delete_transaction = allocation.transaction


####################################################################
#
@receiver(post_delete, sender=TransactionAllocation)
def allocation_post_delete(sender, instance, **kwargs):
    """Recalculate running budget_balance snapshots after an
    allocation is deleted.
    """
    budget = getattr(instance, "_delete_budget", None)
    tx = getattr(instance, "_delete_transaction", None)
    if budget is not None and tx is not None:
        _recalculate_running_balances(budget, tx)
