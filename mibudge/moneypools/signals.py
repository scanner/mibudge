# system imports
#

# 3rd party imports
#
from django.db.models.signals import pre_save
from django.dispatch import receiver

# Project imports
#
from .models import Transaction


####################################################################
#
@receiver(pre_save, sender=Transaction)
def transaction_pre_save(sender, instance, **kwargs):
    """
    Modifications to make to the transaction object before it is
    saved. Things like setting the `description` from the
    `raw_description` if it is not already set.

    Keyword Arguments:
    sender    -- What sent the signal. In our case always Transaction
    instance  -- instance of Transaction object before save
    **kwargs  -- dict
    """
    if not instance.description:
        instance.description = instance.raw_description.strip()
