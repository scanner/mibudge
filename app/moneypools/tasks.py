"""
Celery tasks for the moneypools app.

Tasks here are fired-and-forgotten by signals or views; they run the
kind of work we do not want to block a request on (cross-account
database lookups, bulk reconciliation passes, etc.).
"""

# system imports
import logging

# Project imports
from config import celery_app
from moneypools.models import Transaction
from moneypools.service.linking import attempt_link

logger = logging.getLogger(__name__)


####################################################################
#
@celery_app.task()
def attempt_link_transaction(transaction_id: str) -> None:
    """
    Try to opportunistically link a newly saved Transaction to a
    counterpart on another account the user owns.

    Enqueued from ``transaction_post_save`` via ``on_commit``, so by
    the time this task runs the row is durably in the database.

    Silently returns if the transaction was deleted between enqueue
    and task execution -- a delete path can race with linking and
    there is nothing to do in that case.

    Args:
        transaction_id: UUID of the Transaction to link.
    """
    try:
        tx = Transaction.objects.get(id=transaction_id)
    except Transaction.DoesNotExist:
        logger.info(
            "attempt_link_transaction: Transaction %s no longer exists; "
            "skipping.",
            transaction_id,
        )
        return

    attempt_link(tx)
