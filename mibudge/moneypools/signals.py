# system imports
#

# 3rd party imports
#
from django.db.models.signals import pre_save
from django.dispatch import receiver

# Project imports
#
from .models import Budget, Transaction, InternalTransaction


####################################################################
#
@receiver(pre_save, sender=Transaction)
def transaction_pre_save(sender, instance, **kwargs):
    """
    Modifications to make to the transaction object before it is
    saved. Things like setting the `description` from the
    `raw_description` if it is not already set.

    This is also where the amounts on the budget are credited or debited.

    Keyword Arguments:
    sender    -- What sent the signal. In our case always Transaction
    instance  -- instance of Transaction object before save
    **kwargs  -- dict
    """
    if not instance.description:
        instance.description = instance.raw_description.strip()


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
    if instance.id is None:
        # If this instance of an InternalTransaction has no id, then we
        # debit/credit the src and dst budgets by the amount of this
        # InternalTransaction and save those budgets.
        #
        instance.src_budget.balance -= instance.amount
        instance.dest_budget.balance += instance.amount
        instance.src_budget_balance = instance.src_budget.balance
        instance.dest_budget_balance = instance.dest_budget.balance

        instance.src_budget.save()
        instance.dest_budget.save()
    else:
        # Otherwise we have to adjust the src and dst budgets by the change in
        # the amount of this InternalTransaction between the instance.amount
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

        previous.src_budget += previous.amount
        previous.dest_budget -= previous.amount
        current.src_budget -= current.amount
        current.dest_budget += current.amount

        current.src_budget_balance = current.src_budget.balance
        current.dest_budget_balance = current.dest_budget.balance

        # if current and previous are the same budget then we only need to save
        # one of them.
        #
        current.src_budget.save()
        if current.src_budget != previous.src_budget:
            previous.src_budget.save()
        current.dest_budget.save()
        if current.dest_budget != previous.dest_budget:
            previous.dest_budget.save()
