"""
Celery tasks for the moneypools app.

Tasks here are fired-and-forgotten by signals or views; they run the
kind of work we do not want to block a request on (cross-account
database lookups, bulk reconciliation passes, etc.).

Funding tasks:
    schedule_funding_runs              -- beat-triggered (every 30 min): inspects
                                         each account owner's local time and
                                         enqueues fund_one_account in the
                                         [23:00, 23:30) local-time window and
                                         recur_one_account in the [03:00, 03:30)
                                         local-time window.
    fund_one_account                   -- per-account worker: processes
                                         EventKind.FUND events only.
    recur_one_account                  -- per-account worker: processes
                                         EventKind.RECUR events only.
    prune_funding_event_occurrences    -- weekly: deletes COMPLETE/SKIPPED
                                         FundingEventOccurrence rows whose
                                         scheduled_date is > 365 days old.
"""

# system imports
import logging
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings

# Project imports
from config import celery_app
from moneypools.models import (
    BankAccount,
    EventKind,
    FundingEventOccurrence,
    Transaction,
)
from moneypools.notification_kinds import FUNDING_COMPLETE
from moneypools.service import funding as funding_svc
from moneypools.service.linking import attempt_link
from moneypools.service.shared import funding_system_user
from notifications.service import notify_for

logger = logging.getLogger(__name__)

# Both task types are gated on local-time windows so they fire predictably
# once per day at the right point in the budget cycle:
#
#   FUND  [23:00, 23:30) -- runs in the evening on the fund date (e.g. the
#                           15th or last day of the month), filling the
#                           fill-up goal before midnight.
#   RECUR [03:00, 03:30) -- runs early the next morning on the recur date
#                           (e.g. the 1st of the month), sweeping the
#                           fill-up into the recurring budget after FUND
#                           has had all night to complete.
#
# The 4-hour gap between the windows (23:00 → 03:00 next day) is
# intentional: it gives FUND time to finish filling the fill-up goal
# before the RECUR sweep drains it.
#
_FUND_WINDOW_START = time(23, 0)
_FUND_WINDOW_END = time(23, 30)
_RECUR_WINDOW_START = time(3, 0)
_RECUR_WINDOW_END = time(3, 30)

# Tasks are spread across this many seconds so a burst of accounts does
# not all hit the database at once.  Capped so a small number of accounts
# doesn't stretch unnecessarily.
#
_SPREAD_SECONDS = 1800  # 30 min -- matches scheduler cadence


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
def schedule_funding_runs() -> None:
    """
    Beat-triggered (every 30 min): inspect each account's local time and
    enqueue the appropriate per-account funding worker.

    Accounts with ``auto_funding_enabled=False`` are skipped here -- the
    owner has opted out of automatic funding and will run funding
    manually via the "Run funding now" REST endpoint.

    For each remaining BankAccount, the first owner (ordered by pk)
    supplies the IANA timezone used to compute the owner-local date and
    to decide whether we are inside a task window.  Accounts whose
    owner has an unknown timezone are skipped with a warning.

    fund_one_account is enqueued only in the [23:00, 23:30) local window.
    This places funding in the evening on the fund date (e.g. the 15th
    or last day of the month), consistent with typical payroll deposit
    timing.  FUND events always transfer the full intended amount
    regardless of the Unallocated balance, so no mid-day retry is needed.

    recur_one_account is enqueued only in the [03:00, 03:30) local
    window.  RECUR is one-shot -- there is nothing to retry -- so a
    single fire per day is correct.  The ~4-hour gap between the 23:00
    FUND window and the 03:00 RECUR window gives the fill-up goal time
    to be fully funded before the recurring budget sweep.

    Tasks are spread evenly across up to 30 minutes so a large number
    of accounts does not stampede the database.
    """
    now_utc = datetime.now(tz=UTC)

    # Each tuple: (account_id, local_date_str)
    #   account_id:      BankAccount UUID string
    #   local_date_str:  ISO date in the owner's local timezone (YYYY-MM-DD)
    fund_accounts: list[tuple[str, str]] = []
    recur_accounts: list[tuple[str, str]] = []

    for account in (
        BankAccount.objects.filter(auto_funding_enabled=True)
        .prefetch_related("owners")
        .order_by("pk")
    ):
        owner = account.owners.order_by("pk").first()
        if owner is None:
            logger.debug(
                "schedule_funding_runs: account %s has no owners; skipping.",
                account.id,
            )
            continue

        try:
            tz = ZoneInfo(owner.timezone)
        except ZoneInfoNotFoundError:
            logger.warning(
                "schedule_funding_runs: account %s owner has unknown "
                "timezone %r; skipping.",
                account.id,
                owner.timezone,
            )
            continue

        local_now = now_utc.astimezone(tz)
        local_time = local_now.time()
        local_date_str = local_now.date().isoformat()
        account_id = str(account.id)

        if _FUND_WINDOW_START <= local_time < _FUND_WINDOW_END:
            fund_accounts.append((account_id, local_date_str))
        if _RECUR_WINDOW_START <= local_time < _RECUR_WINDOW_END:
            recur_accounts.append((account_id, local_date_str))

    def _dispatch(
        task,
        pairs: list[tuple[str, str]],
        label: str,
    ) -> None:
        n = len(pairs)
        if n == 0:
            return
        logger.info(
            "schedule_funding_runs: enqueueing %d %s account(s).", n, label
        )
        interval = min(30.0, _SPREAD_SECONDS / n)
        for i, (account_id, local_date_str) in enumerate(pairs):
            task.apply_async(
                args=[account_id],
                kwargs={"local_date_str": local_date_str},
                countdown=int(i * interval),
            )

    _dispatch(fund_one_account, fund_accounts, "fund")
    _dispatch(recur_one_account, recur_accounts, "recur")


########################################################################
########################################################################
#
def _run_funding_task(
    account_id: str,
    local_date_str: str | None,
    kinds: set[EventKind],
    label: str,
) -> None:
    """
    Shared implementation for fund_one_account and recur_one_account.

    Args:
        account_id: UUID of the BankAccount to process.
        local_date_str: ISO date string ('YYYY-MM-DD') representing the
            owner's local date at dispatch time.  Falls back to UTC today
            when None (manual invocation or legacy callers).
        kinds: EventKind set passed through to fund_account().
        label: Task name used in log messages.
    """
    try:
        account = BankAccount.objects.select_related(
            "bank", "unallocated_budget"
        ).get(id=account_id)
    except BankAccount.DoesNotExist:
        logger.warning(
            "%s: BankAccount %s not found; skipping.", label, account_id
        )
        return

    try:
        actor = funding_system_user()
    except Exception as exc:
        logger.error(
            "%s: system user %r missing; Exception: %r  "
            "Check to see if migration 0024_seed_funding_system_user has run.",
            label,
            settings.FUNDING_SYSTEM_USERNAME,
            exc,
        )
        return

    if local_date_str is not None:
        try:
            today = date.fromisoformat(local_date_str)
        except ValueError:
            logger.warning(
                "%s: invalid local_date_str %r; falling back to UTC today.",
                label,
                local_date_str,
            )
            today = date.today()
    else:
        today = date.today()

    report = funding_svc.fund_account(account, today, actor, kinds=kinds)

    if report.busy:
        logger.info(
            "%s: account %s busy -- another worker held the lock.",
            label,
            account_id,
        )
        return

    logger.info(
        "%s: account %s -- %d transfer(s), %d warning(s).",
        label,
        account_id,
        report.transfers,
        len(report.warnings),
    )
    for warning in report.warnings:
        logger.warning("%s: %s: %s", label, account_id, warning)

    if report.funded_budgets:
        notify_for(
            account,
            FUNDING_COMPLETE,
            {
                "account_name": account.name,
                "account_id": str(account.id),
                "date": today.isoformat(),
                "funded_budgets": report.funded_budgets,
                "warnings": report.warnings,
            },
        )


####################################################################
#
@celery_app.task(ignore_result=True)
def fund_one_account(
    account_id: str,
    local_date_str: str | None = None,
) -> None:
    """
    Process due FUND events for one BankAccount.

    Enqueued by schedule_funding_runs in the [23:00, 23:30) local window.
    Uses the owner's local date at dispatch time so the reference date is
    stable even when the worker runs past midnight.

    Args:
        account_id: UUID string of the BankAccount to fund.
        local_date_str: ISO date string ('YYYY-MM-DD') from the scheduler.
            Defaults to UTC today when called manually or from tests.
    """
    _run_funding_task(
        account_id,
        local_date_str,
        kinds={EventKind.FUND},
        label="fund_one_account",
    )


####################################################################
#
@celery_app.task(ignore_result=True)
def recur_one_account(
    account_id: str,
    local_date_str: str | None = None,
) -> None:
    """
    Process due RECUR events for one BankAccount.

    Enqueued by schedule_funding_runs during the [03:00, 03:30) local-
    time window.  Uses the owner's local date at dispatch time.

    Args:
        account_id: UUID string of the BankAccount to process.
        local_date_str: ISO date string ('YYYY-MM-DD') from the scheduler.
            Defaults to UTC today when called manually or from tests.
    """
    _run_funding_task(
        account_id,
        local_date_str,
        kinds={EventKind.RECUR},
        label="recur_one_account",
    )


########################################################################
#
@celery_app.task(ignore_result=True)
def prune_funding_event_occurrences() -> None:
    """
    Delete old COMPLETE and SKIPPED FundingEventOccurrence rows.

    Runs weekly (registered in MANAGED_PERIODIC_TASKS).  Rows whose
    scheduled_date is more than 365 days in the past are eligible for
    deletion regardless of whether they reached COMPLETE or SKIPPED.
    PENDING and PARTIAL rows are never touched.
    """
    cutoff = date.today() - timedelta(days=365)
    deleted, _ = FundingEventOccurrence.objects.filter(
        status__in=[
            FundingEventOccurrence.Status.COMPLETE,
            FundingEventOccurrence.Status.SKIPPED,
        ],
        scheduled_date__lt=cutoff,
    ).delete()
    logger.info(
        "prune_funding_event_occurrences: deleted %d row(s) with "
        "scheduled_date before %s.",
        deleted,
        cutoff,
    )
