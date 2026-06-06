"""
Scrape-sync service.

Reconciles one BankAccount against a fresh bank-side snapshot
supplied by a live scraper (Bank of America today, others later).
The scraper hands the service the full transaction list the bank
just showed it; the service makes the database match.

Why this exists
---------------
The earlier pipeline tried to mutate-in-place an existing pending
Transaction into a posted one by fuzzy-matching descriptions across
scrapes.  Real bank data contradicts that assumption: descriptions
change while a transaction is still pending (`PURCHASE 03/07
ACMECORP CO/BILL ZZ` -> `PURCHASE Acmecorp Co/bill ZZ ON 03/07`)
and again when it posts (`ACH HOLD WIDGETCARD CO PAYMENT ON 03/07`
-> `WIDGETCARD CO DES:PAYMENT ID:837192 INDN:USER NAME CO
ID:XXXXX46721 WEB`).  Description-based matching cannot bridge
those, so both the stale pending row and the new posted row end up
in the database.

The fix is to stop matching.  Pending state is treated as ephemeral:
on every sync the full set of pending rows for the account is wiped
and re-inserted from the scrape.  Posted rows still use the stable
(transaction_date, amount, raw_description) dedup key.

Algorithm
---------
Inside a single `db.atomic()` block, holding the account and
unallocated-budget locks:

1. Delete every pending Transaction (and its lone Unallocated
   TransactionAllocation) for the account.
2. Compute the dedup map of existing posted rows within the scrape's
   date window.
3. Walk the scraped posted rows in reverse order (oldest-on-display
   first) and INSERT INTO Transaction for those not in the dedup map.
   Reverse order makes the highest `created_at` land on the
   newest-on-display row, which is the tiebreaker the UI uses when
   `transaction_date` collides.
4. Walk the scraped pending rows in reverse order and insert them all.
5. Apply the accumulated bank_account / unallocated-budget balance
   deltas in a single save.
6. Recompute per-Transaction snapshot columns
   (`bank_account_available_balance`, `bank_account_posted_balance`)
   and the Unallocated budget's allocation + ITx snapshots.
7. Advance `last_imported_at` / `last_posted_through`.
8. Validate: aggregate balance must equal the scrape's ending_balance;
   a posting-order chain walk must agree row-by-row with the bank's
   per-row running_balance values from the scrape.  Both populate the
   returned report; neither aborts the sync.

Pending Transaction UUIDs are unstable across scrapes by design.
Cross-account `linked_transaction` FKs that pointed at a pending
row get NULL'd (`on_delete=SET_NULL`); the attempt_link_transaction
task re-fires on each new insert and re-establishes the link as soon
as the counterpart appears.

This module is invoked from the
`BankAccountViewSet.sync_scrape` REST action.  It is intentionally
NOT exported via the `transaction` service because it does direct
ORM writes (not service-layer create/delete) to avoid lock
reentrance and the O(M*N) per-tx snapshot recompute cascade those
would trigger.
"""

# system imports
#
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

# 3rd party imports
#
import moneyed

# Project imports
#
from common.locks import acquire_lock
from django.db import transaction as db_transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from notifications.service import notify_for

from moneypools.description_utils import parse_transaction_date
from moneypools.models import (
    BankAccount,
    Budget,
    Transaction,
    TransactionAllocation,
)
from moneypools.notification_kinds import (
    BALANCE_MISMATCH,
    IMPORT_COMPLETE,
    IMPORT_ERROR,
    TRANSACTION_POSTED,
)
from moneypools.service import transaction as transaction_svc
from moneypools.service import (
    transaction_allocation as transaction_allocation_svc,
)

logger = logging.getLogger(__name__)

# How far either side of the scrape's date span to look when building
# the dedup map of existing posted rows.  One day covers timezone
# boundary slop between the scraper's local clock and the stored UTC
# transaction_date.  Grow this if a scrape is ever observed to carry
# transactions whose stored transaction_date drifts further than a day
# from posted_date (none observed in practice so far).
#
_DEDUP_WINDOW_PAD = timedelta(days=1)

# Sentinel epoch used as "from the beginning of time" when telling the
# allocation service to recompute every snapshot on the unallocated
# budget.
#
_EPOCH = datetime.min.replace(tzinfo=UTC)


########################################################################
########################################################################
#
@dataclass
class ScrapedTransaction:
    """One transaction from a bank-side scrape.

    `posted_date` is the bank-supplied settlement datetime for posted
    rows.  For pending rows the bank typically does not publish a
    settlement date yet (BofA renders 'Processing' in the date column;
    other banks use other markers or omit the date entirely) -- the
    scraper substitutes the current local datetime.  The service
    classifies the row purely from `is_pending`; how the scraper
    decided is not its concern.

    The service derives `transaction_date` from the embedded MM/DD
    pattern in `raw_description`, falling back to `posted_date` --
    identical to `transaction.create()`'s logic.

    `running_balance` is the bank-reported balance after this
    transaction was applied, in the bank's *posting* order.  Used only
    for the optional posting-order sanity walk; never persisted.
    """

    is_pending: bool
    posted_date: datetime
    raw_description: str
    amount: moneyed.Money
    transaction_type: str = ""
    running_balance: Decimal | None = None


########################################################################
########################################################################
#
@dataclass
class ScrapeSyncPayload:
    """A complete bank-side snapshot for one account.

    `transactions` is the scrape's natural order -- newest-first as
    the bank renders it.  The service re-orders internally when
    inserting so that `created_at` tiebreakers preserve the scrape's
    top-to-bottom order in the mibudge UI.
    """

    scraped_at: datetime
    ending_balance: moneyed.Money
    transactions: list[ScrapedTransaction]


########################################################################
########################################################################
#
@dataclass
class ScrapeSyncReport:
    """Summary returned to the caller after a sync.

    `balance_mismatch` is the signed difference between the computed
    `account.available_balance` and the scrape's `ending_balance`;
    `None` when they agree exactly.

    `posting_order_mismatches` is a list of human-readable warnings,
    one per row whose posting-order running balance disagrees with the
    bank's per-row `running_balance`.  Empty when every row checks
    out (or when the scrape carried no running balances).
    """

    deleted_pending: int = 0
    inserted_posted: int = 0
    skipped_posted: int = 0
    inserted_pending: int = 0
    balance_mismatch: Decimal | None = None
    posting_order_mismatches: list[str] = field(default_factory=list)
    last_posted_through: date | None = None
    new_transaction_ids: list[str] = field(default_factory=list)
    new_pending_transaction_ids: list[str] = field(default_factory=list)


########################################################################
########################################################################
#
def sync_scrape(
    bank_account: BankAccount,
    payload: ScrapeSyncPayload,
) -> ScrapeSyncReport:
    """Reconcile a BankAccount against a scrape snapshot.

    Acquires the account lock then the unallocated-budget lock (in
    that order per the project's locking convention), opens a single
    `db.atomic()`, and performs the steps documented at the top of
    this module.

    Args:
        bank_account: The BankAccount to sync.  Must have an
            `unallocated_budget` set; `ValueError` is raised
            otherwise.
        payload: The scrape snapshot.  All amounts must use the
            account's currency.

    Returns:
        A `ScrapeSyncReport` summarising what changed and any
        validation warnings.

    Raises:
        ValueError: If the account has no unallocated budget, or any
            scraped amount uses a different currency than the account.
    """
    unalloc = bank_account.unallocated_budget
    if unalloc is None:
        raise ValueError(
            f"BankAccount {bank_account.id} has no unallocated_budget; "
            "cannot sync_scrape."
        )

    account_currency = bank_account.currency
    for stx in payload.transactions:
        if str(stx.amount.currency) != account_currency:
            raise ValueError(
                f"Scraped transaction currency {stx.amount.currency!r} "
                f"does not match account currency {account_currency!r}."
            )
    if str(payload.ending_balance.currency) != account_currency:
        raise ValueError(
            f"Scrape ending_balance currency "
            f"{payload.ending_balance.currency!r} does not match account "
            f"currency {account_currency!r}."
        )

    try:
        with acquire_lock(bank_account.lock_key):
            with acquire_lock(unalloc.lock_key):
                with db_transaction.atomic():
                    report = _sync_scrape_locked(
                        bank_account, unalloc, payload, account_currency
                    )
    except Exception as exc:
        notify_for(
            bank_account,
            IMPORT_ERROR,
            {
                "account_name": bank_account.name,
                "account_id": str(bank_account.id),
                "error": str(exc),
            },
        )
        raise

    # Pending transactions that are no longer pending after this sync.
    # deleted_pending counts all old pending rows wiped; inserted_pending
    # counts those that re-appeared in the new scrape as still-pending.
    # The difference is the net count that actually resolved (posted or
    # cancelled by the bank).
    cleared_pending = max(0, report.deleted_pending - report.inserted_pending)

    notify_for(
        bank_account,
        IMPORT_COMPLETE,
        {
            "account_name": bank_account.name,
            "account_id": str(bank_account.id),
            "new_count": report.inserted_posted,
            "cleared_pending_count": cleared_pending,
            "date": payload.scraped_at.strftime("%Y-%m-%d"),
        },
    )
    _TRANSACTION_DISPLAY_LIMIT = 15

    if report.inserted_posted > 0:
        _new_txns = list(
            Transaction.objects.filter(
                id__in=report.new_transaction_ids, pending=False
            )
            .prefetch_related("allocations__budget")
            .order_by("transaction_date")[: _TRANSACTION_DISPLAY_LIMIT + 1]
        )
        truncated = len(_new_txns) > _TRANSACTION_DISPLAY_LIMIT
        transactions_ctx = [
            {
                "date": tx.transaction_date.strftime("%Y-%m-%d"),
                "description": tx.description,
                "amount": str(tx.amount),
                "budgets": [
                    a.budget.name
                    for a in tx.allocations.all()
                    if a.budget is not None
                ],
            }
            for tx in _new_txns[:_TRANSACTION_DISPLAY_LIMIT]
        ]
        notify_for(
            bank_account,
            TRANSACTION_POSTED,
            {
                "account_name": bank_account.name,
                "account_id": str(bank_account.id),
                "count": report.inserted_posted,
                "date": payload.scraped_at.strftime("%Y-%m-%d"),
                "transactions": transactions_ctx,
                "truncated": truncated,
                "remaining_count": report.inserted_posted
                - _TRANSACTION_DISPLAY_LIMIT
                if truncated
                else 0,
            },
        )
    if report.new_pending_transaction_ids:
        _new_pending = list(
            Transaction.objects.filter(
                id__in=report.new_pending_transaction_ids
            )
            .prefetch_related("allocations__budget")
            .order_by("transaction_date")[: _TRANSACTION_DISPLAY_LIMIT + 1]
        )
        truncated = len(_new_pending) > _TRANSACTION_DISPLAY_LIMIT
        pending_ctx = [
            {
                "date": tx.transaction_date.strftime("%Y-%m-%d"),
                "description": tx.description,
                "amount": str(tx.amount),
                "budgets": [
                    a.budget.name
                    for a in tx.allocations.all()
                    if a.budget is not None
                ],
            }
            for tx in _new_pending[:_TRANSACTION_DISPLAY_LIMIT]
        ]
        count = len(report.new_pending_transaction_ids)
        notify_for(
            bank_account,
            TRANSACTION_POSTED,
            {
                "account_name": bank_account.name,
                "account_id": str(bank_account.id),
                "count": count,
                "date": payload.scraped_at.strftime("%Y-%m-%d"),
                "transactions": pending_ctx,
                "truncated": truncated,
                "remaining_count": count - _TRANSACTION_DISPLAY_LIMIT
                if truncated
                else 0,
                "pending": True,
            },
        )
    if report.balance_mismatch is not None:
        notify_for(
            bank_account,
            BALANCE_MISMATCH,
            {
                "account_name": bank_account.name,
                "account_id": str(bank_account.id),
                "computed_balance": str(bank_account.available_balance.amount),
                "reported_balance": str(payload.ending_balance.amount),
                "diff": f"{report.balance_mismatch:+.2f}",
            },
        )
    return report


########################################################################
########################################################################
#
def _sync_scrape_locked(
    bank_account: BankAccount,
    unalloc: Budget,
    payload: ScrapeSyncPayload,
    account_currency: str,
) -> ScrapeSyncReport:
    """Body of sync_scrape -- runs with locks held inside `atomic()`.

    See module docstring for the algorithm.

    Args:
        bank_account: The locked BankAccount.
        unalloc: The locked unallocated budget.
        payload: The scrape snapshot.
        account_currency: `bank_account.currency` (3-letter ISO code).

    Returns:
        A populated `ScrapeSyncReport`.
    """
    bank_account.refresh_from_db()
    unalloc.refresh_from_db()

    # --- 1. Wipe pending -----------------------------------------------
    pending_qs = Transaction.objects.filter(
        bank_account=bank_account, pending=True
    )
    # `TransactionAllocation.transaction` is a ForeignKey with
    # `to_field='id'`, so its `transaction_id` column stores the
    # Transaction UUID -- not the integer `pkid`.  Mixing the two
    # silently matches zero rows and leaves the unallocated-budget
    # balance unreversed for every wiped pending allocation.  Always
    # use the relation-traversal filter (`transaction__pkid__in=...`)
    # so the FK type is correct.
    pending_pkids = list(pending_qs.values_list("pkid", flat=True))
    deleted_pending = len(pending_pkids)

    # Snapshot existing pending before wipe so we can detect truly new
    # (or changed) pending rows after re-insertion.
    existing_pending_keys: set[tuple[date, Decimal, str]] = {
        (
            row["transaction_date"].date(),
            Decimal(row["amount"]),
            row["raw_description"],
        )
        for row in pending_qs.values(
            "transaction_date", "amount", "raw_description"
        )
    }

    pending_tx_sum = Decimal("0")
    pending_alloc_sum = Decimal("0")
    if pending_pkids:
        pending_tx_sum = Decimal(
            pending_qs.aggregate(total=Coalesce(Sum("amount"), Decimal("0")))[
                "total"
            ]
        )
        pending_allocs = TransactionAllocation.objects.filter(
            transaction__pkid__in=pending_pkids
        )
        pending_alloc_sum = Decimal(
            pending_allocs.aggregate(
                total=Coalesce(Sum("amount"), Decimal("0"))
            )["total"]
        )
        pending_allocs.delete()
        Transaction.objects.filter(pkid__in=pending_pkids).delete()

    # --- 2. Build dedup map for posted ---------------------------------
    scraped_posted = [t for t in payload.transactions if not t.is_pending]
    scraped_pending = [t for t in payload.transactions if t.is_pending]

    # Normalize dates once per scraped posted row.  The parsed
    # `transaction_date` (from the MM/DD embedded in raw_description)
    # is what the dedup query and per-row key both match on, so the
    # window bounds must come from `txn_dt` -- not `posted_date`.
    # A row posted 01/26 with "01/24" in its description parses to
    # transaction_date 01/24; using posted_date 01/26 - pad as the
    # floor would push 01/24 outside the window and miss the existing
    # duplicate.
    posted_normalized: list[tuple[ScrapedTransaction, datetime, datetime]] = [
        (stx, *_normalize_dates(stx)) for stx in scraped_posted
    ]

    # Strict-equality dedup map plus a secondary index keyed by
    # (date, amount) so we can rescue rows whose `raw_description` was
    # truncated by the bank's web UI with a trailing '...'.  BofA
    # truncates older / longer ACH descriptions at roughly the column
    # width (variable per row), so the scraped value can be a prefix
    # of the full description we already have on file (typically from
    # an OFX or CSV import).
    existing_keys: set[tuple[date, Decimal, str]] = set()
    existing_by_date_amount: dict[tuple[date, Decimal], list[str]] = {}
    if posted_normalized:
        min_date = (
            min(txn_dt.date() for _, _, txn_dt in posted_normalized)
            - _DEDUP_WINDOW_PAD
        )
        max_date = (
            max(txn_dt.date() for _, _, txn_dt in posted_normalized)
            + _DEDUP_WINDOW_PAD
        )
        for row in Transaction.objects.filter(
            bank_account=bank_account,
            pending=False,
            transaction_date__date__gte=min_date,
            transaction_date__date__lte=max_date,
        ).values("transaction_date", "amount", "raw_description"):
            row_date = row["transaction_date"].date()
            row_amount = Decimal(row["amount"])
            row_desc = row["raw_description"]
            existing_keys.add((row_date, row_amount, row_desc))
            existing_by_date_amount.setdefault(
                (row_date, row_amount), []
            ).append(row_desc)

    # --- 3. Insert new posted (reverse scrape order) -------------------
    new_tx_ids: list[str] = []
    inserted_posted = 0
    skipped_posted = 0
    posted_delta = Decimal("0")  # accumulated change to posted_balance
    avail_delta = Decimal("0")  # accumulated change to available_balance
    unalloc_delta = Decimal("0")  # accumulated change to unallocated.balance

    # Deletes already applied to in-memory totals via accumulators below;
    # apply them now so subsequent inserts see correct intermediate state
    # if anything needs to read it.
    avail_delta -= pending_tx_sum
    unalloc_delta -= pending_alloc_sum
    # Pending never touched posted_balance, so no posted_delta adjustment
    # from the wipe.

    for stx, posted_dt, txn_dt in reversed(posted_normalized):
        key = (txn_dt.date(), stx.amount.amount, stx.raw_description)
        if key in existing_keys:
            skipped_posted += 1
            continue

        if _matches_truncated(
            stx.raw_description,
            existing_by_date_amount.get((key[0], key[1]), ()),
        ):
            skipped_posted += 1
            continue

        tx = _insert_transaction(
            bank_account=bank_account,
            unalloc=unalloc,
            account_currency=account_currency,
            scraped=stx,
            posted_dt=posted_dt,
            txn_dt=txn_dt,
            pending=False,
        )
        new_tx_ids.append(str(tx.id))
        inserted_posted += 1
        avail_delta += stx.amount.amount
        posted_delta += stx.amount.amount
        unalloc_delta += stx.amount.amount

        # Index the newly-inserted row so a subsequent scraped row in
        # the same payload doesn't slip past via truncation rescue.
        existing_keys.add(key)
        existing_by_date_amount.setdefault((key[0], key[1]), []).append(
            stx.raw_description
        )

    # --- 4. Insert pending (reverse scrape order) ----------------------
    inserted_pending = 0
    new_pending_tx_ids: list[str] = []
    for stx in reversed(scraped_pending):
        posted_dt, txn_dt = _normalize_dates(stx)
        tx = _insert_transaction(
            bank_account=bank_account,
            unalloc=unalloc,
            account_currency=account_currency,
            scraped=stx,
            posted_dt=posted_dt,
            txn_dt=txn_dt,
            pending=True,
        )
        new_tx_ids.append(str(tx.id))
        inserted_pending += 1
        avail_delta += stx.amount.amount
        # pending does NOT touch posted_balance.
        unalloc_delta += stx.amount.amount

        pending_key = (txn_dt.date(), stx.amount.amount, stx.raw_description)
        if pending_key not in existing_pending_keys:
            new_pending_tx_ids.append(str(tx.id))

    # --- 5. Apply accumulated balance deltas ---------------------------
    bank_account.available_balance = moneyed.Money(
        bank_account.available_balance.amount + avail_delta,
        account_currency,
    )
    bank_account.posted_balance = moneyed.Money(
        bank_account.posted_balance.amount + posted_delta,
        account_currency,
    )
    bank_account.save()

    unalloc_balance_currency = str(unalloc.balance.currency)
    unalloc.balance = moneyed.Money(
        unalloc.balance.amount + unalloc_delta,
        unalloc_balance_currency,
    )
    unalloc.save()

    # --- 6. Snapshot refresh -------------------------------------------
    transaction_svc.recompute_transaction_snapshots(bank_account)
    transaction_allocation_svc.recalculate_from_dt(unalloc, _EPOCH)

    # --- 7. last_imported_at / last_posted_through ---------------------
    new_last_posted_through = bank_account.last_posted_through
    if scraped_posted:
        latest_posted = max(t.posted_date.date() for t in scraped_posted)
        if (
            new_last_posted_through is None
            or latest_posted > new_last_posted_through
        ):
            new_last_posted_through = latest_posted

    BankAccount.objects.filter(pkid=bank_account.pkid).update(
        last_imported_at=timezone.now(),
        last_posted_through=new_last_posted_through,
    )
    bank_account.refresh_from_db()

    # --- 8. Aggregate balance validation -------------------------------
    diff = bank_account.available_balance.amount - payload.ending_balance.amount
    balance_mismatch = diff if diff != Decimal("0") else None
    if balance_mismatch is not None:
        logger.warning(
            "sync_scrape: account %s balance mismatch: "
            "computed=%s scrape=%s diff=%+.2f",
            bank_account.id,
            bank_account.available_balance.amount,
            payload.ending_balance.amount,
            diff,
        )

    # --- 9. Posting-order chain validation -----------------------------
    posting_warnings = _validate_posting_order_chain(bank_account, payload)
    for w in posting_warnings:
        logger.warning("sync_scrape: account %s: %s", bank_account.id, w)

    # --- 10. Enqueue cross-account linker for new rows -----------------
    if new_tx_ids:
        # Lazy import: tasks -> linking -> models cycle fires at app
        # ready() if imported at module level.
        from moneypools.tasks import attempt_link_transaction

        def _enqueue_link(tid: str) -> None:
            db_transaction.on_commit(
                lambda: attempt_link_transaction.delay(tid)
            )

        for tid in new_tx_ids:
            _enqueue_link(tid)

    return ScrapeSyncReport(
        deleted_pending=deleted_pending,
        inserted_posted=inserted_posted,
        skipped_posted=skipped_posted,
        inserted_pending=inserted_pending,
        balance_mismatch=balance_mismatch,
        posting_order_mismatches=posting_warnings,
        last_posted_through=new_last_posted_through,
        new_transaction_ids=new_tx_ids,
        new_pending_transaction_ids=new_pending_tx_ids,
    )


########################################################################
########################################################################
#
def _matches_truncated(
    scraped_desc: str,
    candidates: "list[str] | tuple[str, ...]",
) -> bool:
    """Decide if `scraped_desc` is the truncated/full sibling of any candidate.

    BofA's web UI sometimes truncates long ACH descriptions with a
    trailing `...` (length varies row-to-row -- 63 to 66 characters
    were observed in one set of scrapes).  When a scraped row's
    description ends in `...` it should match an existing stored row
    whose full description starts with the scraped stem.  The reverse
    case (existing row is the truncated one, scraped row is full) is
    also handled for robustness.

    Caller guarantees that `candidates` are descriptions of rows that
    already share `(transaction_date, amount)` with the scraped row,
    so a prefix relationship is strong evidence of duplication.

    Args:
        scraped_desc: `raw_description` from the scrape.
        candidates: Existing-row descriptions in the same
            `(date, amount)` bucket.

    Returns:
        True if any candidate is a prefix/extension of `scraped_desc`
        with the `...` truncation marker in play.
    """
    if not candidates:
        return False

    scraped_truncated = scraped_desc.endswith("...")
    scraped_stem = scraped_desc[:-3] if scraped_truncated else scraped_desc

    for cand in candidates:
        if cand == scraped_desc:
            return True
        cand_truncated = cand.endswith("...")
        cand_stem = cand[:-3] if cand_truncated else cand

        # Scraped is truncated: its stem should be a prefix of the
        # candidate's full text.
        if scraped_truncated and cand.startswith(scraped_stem):
            return True
        # Candidate is truncated: its stem should be a prefix of the
        # scraped full text.
        if cand_truncated and scraped_desc.startswith(cand_stem):
            return True

    return False


########################################################################
########################################################################
#
def _normalize_dates(
    scraped: ScrapedTransaction,
) -> tuple[datetime, datetime]:
    """Derive `(posted_date_utc, transaction_date_utc)` from a scrape row.

    Mirrors `transaction.create()`'s logic: the local calendar date
    of `posted_date` is fed to `parse_transaction_date` so the
    MM/DD embedded in `raw_description` resolves correctly across
    year boundaries.

    Args:
        scraped: The scraped transaction.

    Returns:
        A tuple of `(posted_dt_utc, transaction_dt_utc)`.
    """
    posted = scraped.posted_date
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=UTC)
    local_date = posted.date()
    parsed = parse_transaction_date(scraped.raw_description, local_date)
    txn = posted.replace(
        year=parsed.year,
        month=parsed.month,
        day=parsed.day,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    ).astimezone(UTC)
    posted = posted.astimezone(UTC)
    return posted, txn


########################################################################
########################################################################
#
def _insert_transaction(
    bank_account: BankAccount,
    unalloc: Budget,
    account_currency: str,
    scraped: ScrapedTransaction,
    posted_dt: datetime,
    txn_dt: datetime,
    pending: bool,
) -> Transaction:
    """Insert one Transaction + its Unallocated allocation.

    Bypasses `transaction.create` because the bulk sync handles
    locking, balance accumulators, and snapshot recomputation itself.
    The snapshot columns are set to zero here; the caller refreshes
    them in step 6.

    Args:
        bank_account: The locked BankAccount.
        unalloc: The locked unallocated budget.
        account_currency: 3-letter ISO currency code.
        scraped: Source row from the scrape.
        posted_dt: UTC datetime for `posted_date`.
        txn_dt: UTC datetime for `transaction_date`.
        pending: Whether the new row is pending.

    Returns:
        The saved Transaction.
    """
    zero = moneyed.Money(Decimal("0"), account_currency)
    tx = Transaction(
        bank_account=bank_account,
        amount=scraped.amount,  # type: ignore[misc]
        posted_date=posted_dt,
        transaction_date=txn_dt,
        raw_description=scraped.raw_description,
        pending=pending,
        transaction_type=scraped.transaction_type,
        # Snapshot columns are filled in by
        # transaction_svc.recompute_transaction_snapshots after all
        # inserts are done; the placeholders here are overwritten.
        bank_account_available_balance=zero,
        bank_account_posted_balance=zero,
    )
    tx.save()

    alloc = TransactionAllocation(
        transaction=tx,
        budget=unalloc,
        amount=scraped.amount,  # type: ignore[misc]
    )
    alloc.save()

    return tx


########################################################################
########################################################################
#
def _validate_posting_order_chain(
    bank_account: BankAccount,
    payload: ScrapeSyncPayload,
) -> list[str]:
    """Walk our transactions in posting order; compare to bank's chain.

    The bank renders one running balance per row in *posting* order
    (most recent settled first).  Our stored
    `bank_account_*_balance` columns are in *display* order
    (`-transaction_date, -created_at`).  These chains disagree
    whenever `posted_date != transaction_date` for some row.

    To audit the sync we re-derive the posting-order chain in memory:
    sort the scrape's posted rows by `posted_date` ascending, walk
    forward applying each amount to a running total starting from the
    earliest scraped row's `running_balance - amount`, then compare
    to the bank's per-row `running_balance`.  A mismatch indicates
    that a transaction is missing, duplicated, or has the wrong
    amount.

    Pending transactions in the scrape are skipped -- banks
    typically only publish a running_balance column for settled rows.

    Args:
        bank_account: The synced account (for logging context).
        payload: The scrape snapshot.

    Returns:
        Zero or more warning strings.  Empty list means everything
        agrees, or the scrape carried no per-row running balances.
    """
    warnings: list[str] = []

    posted_rows = [t for t in payload.transactions if not t.is_pending]
    rows_with_rb = [t for t in posted_rows if t.running_balance is not None]
    if not rows_with_rb:
        return warnings

    # Walk the bank's chain in newest-first order (scrape order).  For
    # each consecutive pair the difference between running balances
    # should equal the amount of the newer row.  Any disagreement
    # points at a row we inserted with the wrong amount, or a missing
    # / extra row in between.
    for i in range(len(rows_with_rb) - 1):
        newer = rows_with_rb[i]
        older = rows_with_rb[i + 1]
        # The `is not None` filter above guarantees both are non-None;
        # the local bindings make that obvious to the type checker.
        newer_rb = newer.running_balance
        older_rb = older.running_balance
        assert newer_rb is not None and older_rb is not None
        # newer_rb == older_rb + newer.amount, because newer was applied
        # after older.
        expected = older_rb + newer.amount.amount
        if expected != newer_rb:
            warnings.append(
                f"posting-order mismatch between "
                f"{newer.posted_date.date()} {newer.raw_description!r} "
                f"({newer.amount.amount:+}) and "
                f"{older.posted_date.date()} {older.raw_description!r}: "
                f"expected running_balance={expected}, got {newer_rb}"
            )

    return warnings
