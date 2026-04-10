# system imports
#
from datetime import UTC, datetime

# 3rd party imports
#
from django.db.models.signals import post_save, pre_delete, pre_save
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
# XXX Maybe the unallocated budget should be an object assigned to the bank
#     account? (and then we do not care what its name is..)
#
UNALLOCATED_BUDGET_NAME = "Unallocated"  # XXX I18N this..


####################################################################
#
@receiver(pre_save, sender=BankAccount)
def bank_account_pre_save(sender, instance, **kwargs):
    """
    When a bank account is created
    """
    pass


####################################################################
#
@receiver(post_save, sender=BankAccount)
def bank_account_post_save(sender, instance, created, **kwargs):
    """
    After a bank account is saved. This is where we create and setup the
    'unallocated budget'.
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

    if allocation.pkid is None:
        # New allocation: credit the budget by the allocation amount.
        #
        allocation.budget.balance += allocation.amount
        allocation.budget.save()
        allocation.budget_balance = allocation.budget.balance
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
            allocation.budget_balance = allocation.budget.balance

        # If the amount changed, adjust the budget balance by the delta.
        #
        if previous.amount != allocation.amount:
            allocation.budget.balance -= previous.amount
            allocation.budget.balance += allocation.amount
            allocation.budget.save()
            allocation.budget_balance = allocation.budget.balance


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


####################################################################
#
@receiver(pre_save, sender=InternalTransaction)
def internal_transaction_pre_save(sender, instance, **kwargs):
    """
    This is what lets us modify the src & dst budgets to credit/debit
    the right amounts.

    Keyword Arguments:
    sender    -- What sent the signal. In our case always InternalTransaction
    instance  -- instance of InternalTransaction object before save
    **kwargs  -- dict
    """
    # Internal transactions are a transfer from budget A to budget B.
    # As such the amount is never negative. If you want to transfer
    # from B to A, you would make that internal transaction. Not an
    # internal transaction from A to B with a negative amount.
    #
    if instance.amount.amount < 0:
        raise ValueError(f"Amount must not be negative: {instance.amount}")

    if instance.pkid is None:
        # If this instance of an InternalTransaction has no id, then we
        # debit/credit the src and dst budgets by the amount of this
        # InternalTransaction and save those budgets.
        #
        instance.src_budget.balance -= instance.amount
        instance.dst_budget.balance += instance.amount
        instance.src_budget_balance = instance.src_budget.balance
        instance.dst_budget_balance = instance.dst_budget.balance

        instance.src_budget.save()
        instance.dst_budget.save()
    else:
        # Otherwise we have to adjust the src and dst budgets by the change in
        # the amount of this InternalTransaction between the inst.amount
        # and the amount that is saved in the db.
        #
        # XXX This should generally not happen because the src budget, dst
        #     budget, and amount are NOT editable so no user UI action should
        #     cause this to happen. However, we need to properly account for
        #     this case as it is possible to modify these fields and save the
        #     InternalTransaction inside code.
        #
        current = instance
        previous = InternalTransaction.objects.get(id=instance.id)

        # XXX This could be made more efficient by only loading and saving
        #     different budgets from the ORM if they are different. But doing
        #     it this brute force way makes the code easier to read and
        #     debug. This operation should not be happening often so I believe
        #     this is okay.
        #
        # XXX we should really only do this if the amount is different or
        #     either of the src or dst budgets are different between the
        #     previous incarnation of this transaction and the current one.
        #
        previous.src_budget.balance += previous.amount
        previous.dst_budget.balance -= previous.amount
        previous.src_budget.save()
        previous.dst_budget.save()

        current.src_budget = Budget.objects.get(id=current.src_budget.id)
        current.dst_budget = Budget.objects.get(id=current.dst_budget.id)

        current.src_budget.balance -= current.amount
        current.dst_budget.balance += current.amount
        current.src_budget_balance = current.src_budget.balance
        current.dst_budget_balance = current.dst_budget.balance
        current.src_budget.save()
        current.dst_budget.save()


####################################################################
#
@receiver(pre_delete, sender=InternalTransaction)
def internal_transaction_pre_delete(sender, instance, **kwargs):
    """
    The intent is that internal transactions (moving money between
    budgets) are never deleted. If a user wishes to undo an internal
    transaction they will create a new internal transaction reversing
    the previous transaction.

    However various book keeping and bug cleanup processes may require
    that we delete internal transactions and when that happens the
    adjustments to the associated budgets balances need to be
    reversed.

    Keyword Arguments:
    sender    -- What sent the signal. In our case always InternalTransaction
    instance  -- instance of InternalTransaction object before save
    **kwargs  -- dict
    """
    instance.src_budget.balance += instance.amount
    instance.dst_budget.balance -= instance.amount
    # XXX We are deleting this instance so these lines are not necessary but it
    #     feels kind of wrong to not update them..
    #
    instance.src_budget_balance = instance.src_budget.balance
    instance.dst_budget_balance = instance.dst_budget.balance

    instance.src_budget.save()
    instance.dst_budget.save()
