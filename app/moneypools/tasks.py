"""
Celery tasks for the moneypools app.

Tasks here are fired-and-forgotten by signals or views; they run the
kind of work we do not want to block a request on (cross-account
database lookups, bulk reconciliation passes, etc.).

Funding tasks:
    fund_all_accounts -- beat-triggered fan-out: enqueues fund_one_account
                         for every active BankAccount.
    fund_one_account  -- per-account worker: calls funding_svc.fund_account()
                         and logs the result.
"""

# system imports
import logging
from datetime import date

from django.conf import settings

# Project imports
from config import celery_app
from moneypools.models import BankAccount, Transaction
from moneypools.service import funding as funding_svc
from moneypools.service.linking import attempt_link
from moneypools.service.shared import funding_system_user

logger = logging.getLogger(__name__)


####################################################################
#
@celery_app.task(ignore_result=True)
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


########################################################################
########################################################################
#
@celery_app.task(ignore_result=True)
def fund_all_accounts() -> None:
    """
    Beat-triggered fan-out: enqueue fund_one_account for every BankAccount.

    Runs daily.  Skips accounts with no budgets; per-account work (gate
    check, event collection, transfers) runs in individual worker tasks
    so a slow or deferred account does not block others.
    """
    account_ids = list(BankAccount.objects.values_list("id", flat=True))
    n = len(account_ids)
    logger.info("fund_all_accounts: enqueueing %d account(s).", n)
    # Spread tasks evenly across up to 1 hour; cap spacing at 60 s so a
    # small number of accounts doesn't stretch unnecessarily.
    interval = min(60.0, 3600.0 / max(n, 1))
    for i, account_id in enumerate(account_ids):
        fund_one_account.apply_async(
            args=[str(account_id)],
            countdown=int(i * interval),
        )


####################################################################
#
@celery_app.task(ignore_result=True)
def fund_one_account(account_id: str) -> None:
    """
    Process due funding and recurrence events for one BankAccount.

    Enqueued by fund_all_accounts.  Uses today's UTC date as the
    reference date.  Logs a summary and any warnings; deferred accounts
    are logged at INFO level (not warnings -- deferral is normal when
    imports are behind).

    Args:
        account_id: UUID string of the BankAccount to fund.
    """
    try:
        account = BankAccount.objects.select_related(
            "bank", "unallocated_budget"
        ).get(id=account_id)
    except BankAccount.DoesNotExist:
        logger.warning(
            "fund_one_account: BankAccount %s not found; skipping.",
            account_id,
        )
        return

    try:
        actor = funding_system_user()
    except Exception as exc:
        logger.error(
            "fund_one_account: user %r missing; Exception: %r"
            "Check to see if migration 0024_seed_funding_system_user has run.",
            settings.FUNDING_SYSTEM_USERNAME,
            exc,
        )
        return

    today = date.today()
    report = funding_svc.fund_account(account, today, actor)

    if report.deferred:
        logger.info(
            "fund_one_account: account %s deferred (last_posted_through=%s).",
            account_id,
            account.last_posted_through,
        )
        return

    logger.info(
        "fund_one_account: account %s -- %d transfer(s), %d warning(s).",
        account_id,
        report.transfers,
        len(report.warnings),
    )
    for warning in report.warnings:
        logger.warning("fund_one_account: %s: %s", account_id, warning)
