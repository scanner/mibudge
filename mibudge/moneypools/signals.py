# system imports
#
from datetime import datetime

# 3rd party imports
#
from django.db.models.signals import post_save, pre_delete, pre_save
from django.dispatch import receiver
from pytz import UTC

# Project imports
#
from .models import BankAccount, Budget, InternalTransaction, Transaction

# To make our logic simpler every bank account will always have an unallocated
# budget. This budget is creatd when the bank account is first saved. We do not
# allow the creation of any other budget associated with a bank account to have
# the same name. The user may not delete/archive this budget.
#
# If a Transaction is created and a budget is not associated with it, it will
# be assocaited with the Unallocated budget.
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
            target_date=datetime.now(UTC),
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
    Modifications to make to the transaction object before it is
    saved. Things like setting the `description` from the
    `raw_description` if it is not already set.

    This is also where the amounts on the budget are credited or debited.

    NOTE: Transactions can not change bank accounts (but they can change
    budgets)

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

    # All transactions must be associated with a budget. If no budget was
    # specified then we will associate it with the bank account's "unallocated
    # budget"
    #
    # TODO: In the future we will use information provided by the user to
    #       determine what budget to associate this transaction with by
    #       default.
    #
    if transaction.budget is None:
        transaction.budget = transaction.bank_account.unallocated_budget

    # If the pkid is None then this is a newly created Transaction that has not
    # yet been saved to the db. This part of the `if` clause deals with newly
    # created transactions.
    #
    if transaction.pkid is None:
        # Update the bank account's available & posted balance.
        # Update the associated budget's balance.
        #
        transaction.bank_account.available_balance += transaction.amount
        transaction.bank_account_available_balance = (
            transaction.bank_account.available_balance
        )
        # If this transaction is not pending, then also update the the posted
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

        transaction.budget.balance += transaction.amount
        transaction.budget.save()
        transaction.budget_balance = transaction.budget.balance
    else:
        # We only reach here if this transaction already exists and it is being
        # updated. So we need to compare in-memory transaction object with what
        # is already saved in the db to determine how to update related objects
        # and fields.
        #
        previous = Transaction.objects.get(id=transaction.id)

        # If the associated budget has changed then we need to adjust the
        # previous and current budgets.
        #
        # NOTE: We are adjusting both the previous budget and the
        #       transacation's current budget by the _previous_ amount of the
        #       transaction. In the following `if` clause where we check if
        #       the transaction amount is different is where we will modify
        #       the currently assigned budget's balance by the transaction's
        #       new amount.
        #
        if previous.budget != transaction.budget:
            previous.budget.balance -= previous.amount
            previous.budget_balance = previous.budget.balance
            transaction.budget.balance += previous.amount
            transaction.budget_balance = transaction.budget.balance
            previous.budget.save()
            transaction.budget.save()

        # If the amount of the transaction has changed then we need to
        # change the bank accounts available amount and the associated
        # budget's available amount.
        #
        save_bank_account = False
        if previous.amount != transaction.amount:
            transaction.bank_account.available_balance -= previous.amount
            transaction.bank_account.available_balance += transaction.amount

            transaction.budget.balance -= previous.amount
            transaction.budget.balance += transaction.amount
            transaction.budget_balance = transaction.budget.balance
            transaction.budget.save()

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
    Transactions in general will never be deleted but I can see doing cleanup
    operations while debugging and testing that require their deletion and in
    that case we need to make sure that the associated bank account and
    budgets values are updated properly

    TODO
    """
    transaction = instance  # To make the code easier to read

    # Update the associated budget's balance.
    #
    if transaction.budget is not None:
        transaction.budget.balance -= transaction.amount
        transaction.budget.save()

    # Update the bank account's available & posted balance.
    #
    if transaction.bank_account:
        transaction.bank_account.available_balance -= transaction.amount

        # If this transaction is not pending, then also update the the posted
        # amount for the bank account.
        #
        if not transaction.pending:
            transaction.bank_account.posted_balance -= transaction.amount
        transaction.bank_account.save()


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
        # XXX This should generally not happen beacuse the src budget, dst
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
