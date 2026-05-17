"""
Import live Bank of America transactions into mibudge via its REST API.

Logs into Bank of America using the bofa_scraper Selenium/Firefox scraper,
scrapes all accessible accounts, and submits their transactions through the
same dedup + POST pipeline used by the CSV/OFX importers.

Requires the importers-bofa optional dependency group::

    uv sync --group importers-bofa
    uv run --group importers-bofa python -m importers.import_bofa_live

BofA credentials are read from BOFA_ID and BOFA_PASSCODE environment variables
or the --bofa-id / --bofa-passcode flags.  mibudge credentials follow the same
resolution order as the CSV importer (CLI flags > env vars > .env > Vault).

2FA: if BofA requires it, the scraper prompts for the code interactively via
stdin.  Run with --no-headless to watch the browser.

Scraper behaviour verified against all 4 accounts via
~/src/bank_project/bofa_test/bofa_test.py (2026-05-13):

* Amount signs are correct -- BofA renders debits as ``-$xx.xx`` in the
  amount-cell so the scraped floats are already negative for debits.
* Pending transactions show ``"Processing"`` in the date-cell (not a
  parseable date) and ``"Debit"`` / ``"Virtual Card"`` etc. in the
  type-cell (not ``"Pending"``).  Pending detection relies solely on the
  date parse failing.
* Account names follow the pattern ``NAME - XXXX`` where XXXX is the
  last 4 digits used to match the mibudge BankAccount.
"""

# system imports
import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

# 3rd party imports
import click
from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

# Project imports
from importers.client import AuthenticationError
from importers.import_transactions import (
    ImportResult,
    _build_client,
    _fetch_existing,
    _mark_imported,
    _resolve_account_by_query,
    _run_funding,
    import_statement,
)
from importers.parsers.bofa_csv import _infer_transaction_type
from importers.parsers.common import ParsedStatement, ParsedTransaction
from importers.theme import get_theme, theme_option

logger = logging.getLogger(__name__)

SCRAPE_FORMAT_VERSION = 2


########################################################################
########################################################################
#
@dataclass
class SavedTransaction:
    """One transaction as scraped from the BofA activity table.

    Field names match what bofa_scraper's transaction objects expose so
    that a list of these can be fed directly to ``_build_statement`` via
    ``_ReplayAccount``.  ``date`` is the raw BofA string -- e.g.
    ``"05/07/2026"`` for settled transactions and ``"Processing"`` for
    pending ones.

    ``txn_hash`` is the BofA-supplied per-transaction SHA-256 hash scraped
    from the ``data-txnhash`` attribute of the view-transaction-details
    element.  It is stable across pending and settled states.
    Empty string for files saved before format_version 2.

    ``running_balance`` is the available balance after this transaction
    as shown in BofA's activity table.  Used to validate the
    walk-backward computation in ``_build_statement``.  "0.00" for files
    saved before format_version 2.
    """

    date: str
    desc: str
    amount: str
    type: str
    txn_hash: str = ""
    running_balance: str = "0.00"


########################################################################
########################################################################
#
@dataclass
class SavedScrape:
    """Complete scrape result for one BofA account.

    Stores the raw pre-``_build_statement`` data so that replay produces
    identical results to the original run and the raw date strings remain
    comparable with CSV exports.
    """

    format_version: int
    scraped_at: str
    account_name: str
    ending_balance: str
    transactions: list[SavedTransaction]


########################################################################
########################################################################
#
def save_scraped_account(
    account: Any,
    save_dir: Path,
    scraped_at: datetime,
) -> Path:
    """Serialize a scraped BofA account to a JSON file.

    Args:
        account: bofa_scraper Account with transactions populated.
        save_dir: Directory to write the file into.
        scraped_at: Timestamp of the scrape (UTC).

    Returns:
        Path to the written file.
    """
    last_four = _extract_last_four(account.get_name()) or "xxxx"
    ts = scraped_at.strftime("%Y-%m-%d-%H%M%S")
    filename = save_dir / f"{ts}-{last_four}.json"

    raw_txs = account.get_transactions()
    saved = SavedScrape(
        format_version=SCRAPE_FORMAT_VERSION,
        scraped_at=scraped_at.isoformat(),
        account_name=account.get_name(),
        ending_balance=str(
            Decimal(str(account.get_balance())).quantize(Decimal("0.01"))
        ),
        transactions=[
            SavedTransaction(
                date=tx.date,
                desc=tx.desc,
                amount=str(Decimal(str(tx.amount)).quantize(Decimal("0.01"))),
                type=tx.type,
                txn_hash=getattr(tx, "txn_hash", ""),
                running_balance=str(
                    Decimal(str(getattr(tx, "running_balance", 0))).quantize(
                        Decimal("0.01")
                    )
                ),
            )
            for tx in raw_txs
        ],
    )

    save_dir.mkdir(parents=True, exist_ok=True)
    filename.write_text(json.dumps(asdict(saved), indent=2), encoding="utf-8")
    return filename


########################################################################
########################################################################
#
def load_saved_scrape(path: Path) -> SavedScrape:
    """Load a saved scrape JSON file.

    Args:
        path: Path to a JSON file written by ``save_scraped_account``.

    Returns:
        The deserialized ``SavedScrape``.

    Raises:
        ValueError: If the file has an unsupported format version.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    version = data.get("format_version", 0)
    if version not in (1, SCRAPE_FORMAT_VERSION):
        raise ValueError(
            f"{path}: unsupported format_version {version} "
            f"(expected {SCRAPE_FORMAT_VERSION})"
        )
    txs: list[SavedTransaction] = []
    for tx in data["transactions"]:
        if version == 1:
            # txn_hash and running_balance were added in format_version 2.
            txs.append(
                SavedTransaction(
                    date=tx["date"],
                    desc=tx["desc"],
                    amount=tx["amount"],
                    type=tx["type"],
                )
            )
        else:
            txs.append(SavedTransaction(**tx))
    return SavedScrape(
        format_version=version,
        scraped_at=data["scraped_at"],
        account_name=data["account_name"],
        ending_balance=data["ending_balance"],
        transactions=txs,
    )


########################################################################
########################################################################
#
def _normalize_description(text: str) -> str:
    """Collapse internal whitespace to match CSV-imported raw_description values."""
    return " ".join(text.split())


####################################################################
#
def _resolve_truncated_descriptions(
    statement: ParsedStatement,
    existing: dict[tuple[str, str, str], list[tuple[str, str, str]]],
) -> ParsedStatement:
    """
    Replace scraper-truncated descriptions with their full stored versions.

    BofA's activity table truncates long ACH descriptions with a literal
    '...' suffix (e.g. 'APPLE GS SAVINGS ... CO...' instead of the full
    '...CO ID:XXXXX99999 WEB').  The CSV export has the full string, so
    when a prior CSV import is followed by a live-scraper run the dedup
    key (date, amount, description) mismatches and a duplicate is created.

    For each scraped transaction that has no exact match in ``existing``,
    this function checks whether any existing entry with the same date and
    amount has a description that starts with the scraped text (after
    stripping a trailing '...').  When found, it replaces the scraped
    description with the stored full version so the normal dedup path
    catches it.

    Args:
        statement: Statement built from scraped data.
        existing: Pre-fetched dedup map from ``_fetch_existing``.

    Returns:
        A new ``ParsedStatement`` with resolved descriptions.
    """
    # Index existing keys by (date_str, amount_str) for fast prefix lookup.
    da_index: dict[tuple[str, str], list[str]] = {}
    for date_str, amount_str, desc in existing:
        da_index.setdefault((date_str, amount_str), []).append(desc)

    resolved: list[ParsedTransaction] = []
    for tx in statement.transactions:
        date_str = tx.transaction_date.isoformat()
        amount_str = str(tx.amount.quantize(Decimal("0.01")))
        scraped = tx.raw_description

        # Nothing to do if the exact key already matches.
        if (date_str, amount_str, scraped) in existing:
            resolved.append(tx)
            continue

        prefix = scraped[:-3] if scraped.endswith("...") else scraped
        candidates = da_index.get((date_str, amount_str), [])
        full_desc = next(
            (d for d in candidates if d != scraped and d.startswith(prefix)),
            None,
        )

        if full_desc:
            logger.debug(
                "Resolved truncated description %r -> %r", scraped, full_desc
            )
            resolved.append(
                ParsedTransaction(
                    transaction_date=tx.transaction_date,
                    raw_description=full_desc,
                    amount=tx.amount,
                    running_balance=tx.running_balance,
                    transaction_type=tx.transaction_type,
                    pending=tx.pending,
                    bank_transaction_id=tx.bank_transaction_id,
                )
            )
        else:
            resolved.append(tx)

    return ParsedStatement(
        beginning_balance=statement.beginning_balance,
        beginning_date=statement.beginning_date,
        ending_balance=statement.ending_balance,
        ending_date=statement.ending_date,
        total_credits=statement.total_credits,
        total_debits=statement.total_debits,
        transactions=resolved,
        source_path=statement.source_path,
    )


####################################################################
#
def _parse_scraped_date(date_str: str) -> tuple[date, bool]:
    """
    Parse a date string from bofa_scraper's date-cell.

    Args:
        date_str: Date text from the BofA UI (e.g. "01/07/2025" or
            "Processing" for pending/in-flight transactions).

    Returns:
        A ``(date, is_pending)`` tuple.  Returns ``(today, True)`` when the
        string cannot be parsed as MM/DD/YYYY -- BofA shows "Processing" in
        the date cell for pending transactions instead of a real date.
    """
    try:
        return datetime.strptime(date_str.strip(), "%m/%d/%Y").date(), False
    except ValueError:
        return date.today(), True


####################################################################
#
def _extract_last_four(account_name: str) -> str | None:
    """
    Extract the last 4-digit sequence from a BofA account name.

    Handles formats like "Checking ...1234", "Adv Plus - 1234.", "(1234)".

    Args:
        account_name: BofA account name from ``account.get_name()``.

    Returns:
        The 4-digit string, or None if no 4-digit run is found.
    """
    m = re.search(r"(\d{4})\D*$", account_name)
    return m.group(1) if m else None


####################################################################
#
def _build_statement(account: Any) -> ParsedStatement:
    """
    Build a ParsedStatement from a fully-scraped BofA Account.

    The current account balance is used as the ending_balance.  Only
    settled transactions contribute to balance calculations; pending
    transactions (detected via the date-cell showing "Processing") are
    included with ``pending=True``.

    Running balances for settled transactions are computed by walking
    backward from ``ending_balance``.  When the scraper supplies a
    per-transaction running_balance (format_version >= 2), each
    computed value is validated against the scraped value; a mismatch
    indicates a missing transaction and is logged as a warning.

    Each transaction's ``txn_hash`` (the BofA-supplied SHA-256 hash from
    the ``data-txnhash`` attribute) is stored as ``bank_transaction_id``
    on the ``ParsedTransaction`` so the import pipeline can deduplicate
    by stable ID rather than by the (date, amount, description) 3-tuple.

    NOTE: ``validate_statement`` is intentionally NOT called -- pending
    transactions break the balance-walk formula used by that function.

    Args:
        account: A bofa_scraper ``Account`` with transactions populated.

    Returns:
        A ``ParsedStatement`` ready for ``import_statement()``.
    """
    raw_txs = account.get_transactions()
    ending_balance = Decimal(str(account.get_balance())).quantize(
        Decimal("0.01")
    )
    acct_name = account.get_name()

    # Pairs of (ParsedTransaction, scraped_running_balance_or_None)
    # kept together so we can validate after the walk.
    settled_pairs: list[tuple[ParsedTransaction, Decimal | None]] = []
    pending: list[ParsedTransaction] = []

    for tx in raw_txs:
        tx_date, is_pending = _parse_scraped_date(tx.date)
        # NOTE: the type-cell shows "Debit"/"Virtual Card"/etc. for pending
        # rows (not "Pending"), so pending detection relies solely on the
        # date-cell showing "Processing" -- verified via bofa_test.py.
        amount = Decimal(str(tx.amount)).quantize(Decimal("0.01"))
        raw_description = _normalize_description(tx.desc)
        bank_tx_id: str | None = getattr(tx, "txn_hash", "") or None
        scraped_running_balance: Decimal | None = None
        raw_rb = getattr(tx, "running_balance", None)
        if raw_rb is not None:
            try:
                scraped_running_balance = Decimal(str(raw_rb)).quantize(
                    Decimal("0.01")
                )
            except Exception:
                pass

        logger.debug(
            "raw tx: date=%r type=%r amount=%s desc=%r pending=%s txn_hash=%r",
            tx.date,
            tx.type,
            tx.amount,
            tx.desc,
            is_pending,
            bank_tx_id,
        )

        transaction_type = _infer_transaction_type(raw_description, amount)
        parsed = ParsedTransaction(
            transaction_date=tx_date,
            raw_description=raw_description,
            amount=amount,
            running_balance=Decimal("0"),  # placeholder; filled in below
            transaction_type=transaction_type,
            pending=is_pending,
            bank_transaction_id=bank_tx_id,
        )
        if is_pending:
            pending.append(parsed)
        else:
            settled_pairs.append((parsed, scraped_running_balance))

    # BofA's avail-balance-cell records the *posted* running balance at each
    # settled transaction (pending not yet deducted), while account.get_balance()
    # returns the *available* balance (current pending already deducted).  Walk
    # backward from the posted ending balance so the validation check compares
    # like with like.
    pending_total = sum(tx.amount for tx in pending)
    posted_ending_balance = ending_balance - pending_total

    # Walk backward in original scraper order (newest-first).  Do NOT pre-sort
    # by date before the walk: stable sort preserves scraper order within same-
    # date groups, so reversed(sorted) would process same-date items oldest-
    # first -- wrong for the walk.  Iterating in scraper order processes the
    # most-recent transaction first, which is what the walk-backward requires.
    running = posted_ending_balance
    settled_final: list[ParsedTransaction] = []
    for parsed_tx, scraped_rb in settled_pairs:
        computed_rb = running
        settled_final.append(
            ParsedTransaction(
                transaction_date=parsed_tx.transaction_date,
                raw_description=parsed_tx.raw_description,
                amount=parsed_tx.amount,
                running_balance=computed_rb,
                transaction_type=parsed_tx.transaction_type,
                pending=False,
                bank_transaction_id=parsed_tx.bank_transaction_id,
            )
        )
        if (
            scraped_rb is not None
            and scraped_rb != Decimal("0.00")
            and computed_rb != scraped_rb
        ):
            logger.warning(
                "%s: running_balance mismatch for %r on %s: "
                "computed=%s scraped=%s -- possible missing transaction",
                acct_name,
                parsed_tx.raw_description,
                parsed_tx.transaction_date,
                computed_rb,
                scraped_rb,
            )
        running -= parsed_tx.amount
    # Reverse to oldest-first for chronological import.
    settled_final.reverse()
    beginning_balance = running

    # Pending transactions: bank_transaction_id is stored for dedup;
    # running_balance is not meaningful here.
    pending_final = [
        ParsedTransaction(
            transaction_date=tx.transaction_date,
            raw_description=tx.raw_description,
            amount=tx.amount,
            running_balance=ending_balance,
            transaction_type=tx.transaction_type,
            pending=True,
            bank_transaction_id=tx.bank_transaction_id,
        )
        for tx in pending
    ]

    today = date.today()
    settled_dates = [tx.transaction_date for tx in settled_final]
    beginning_date = min(settled_dates) if settled_dates else today
    ending_date = max(settled_dates) if settled_dates else today

    total_credits = sum(
        (tx.amount for tx in settled_final if tx.amount > 0), Decimal("0")
    )
    total_debits = sum(
        (tx.amount for tx in settled_final if tx.amount < 0), Decimal("0")
    )

    logger.info(
        "%s: %d settled, %d pending; ending_balance=%s beginning_balance=%s",
        acct_name,
        len(settled_final),
        len(pending_final),
        ending_balance,
        beginning_balance,
    )

    return ParsedStatement(
        beginning_balance=beginning_balance,
        beginning_date=beginning_date,
        ending_balance=ending_balance,
        ending_date=ending_date,
        total_credits=total_credits,
        total_debits=total_debits,
        transactions=settled_final + pending_final,
        source_path=f"live:{acct_name}",
    )


########################################################################
########################################################################
#
def _resolve_pending_transactions(
    statement: ParsedStatement,
    bank_account_id: str,
    client: Any,
    user_timezone: str,
    dry_run: bool = False,
) -> ImportResult:
    """Match settled scraped transactions against pending DB rows and resolve them.

    For each settled scraped transaction, looks for a pending transaction in
    mibudge that has the same ``raw_description`` and a ``posted_date`` within
    5 calendar days.  When a match is found, calls the ``resolve-pending``
    endpoint to atomically transition the pending row to posted.

    Must run BEFORE ``_fetch_existing`` so that resolved rows appear in the
    dedup map and the normal import path skips them.

    Args:
        statement: Statement built from scraped data (settled + pending).
        bank_account_id: UUID of the mibudge BankAccount.
        client: Authenticated ``MibudgeClient``.
        user_timezone: User's timezone string (for date normalisation).
        dry_run: When True, log matches but do not POST to the API.

    Returns:
        An ``ImportResult`` with only ``resolved`` and
        ``resolved_amount_changed`` populated.
    """
    result = ImportResult()

    settled_txs = [tx for tx in statement.transactions if not tx.pending]
    if not settled_txs:
        return result

    # Fetch all pending transactions for this account from the DB.
    pending_db: list[dict[str, Any]] = list(
        client.get_all(
            "/api/v1/transactions/",
            params={"bank_account": bank_account_id, "pending": "true"},
        )
    )
    if not pending_db:
        return result

    logger.debug(
        "resolve_pending: %d settled scraped, %d pending in DB",
        len(settled_txs),
        len(pending_db),
    )

    # Index pending DB rows by bank_transaction_id (primary) and
    # raw_description (fallback) for O(1) lookup.
    pending_by_bank_id: dict[str, dict[str, Any]] = {}
    pending_by_desc: dict[str, list[dict[str, Any]]] = {}
    for row in pending_db:
        btid = row.get("bank_transaction_id")
        if btid:
            pending_by_bank_id[btid] = row
        desc = row["raw_description"]
        pending_by_desc.setdefault(desc, []).append(row)

    MAX_DATE_DELTA = 5  # calendar days

    def _resolve_row(
        matched_row: dict[str, Any],
        settle_date: date,
        tx: ParsedTransaction,
    ) -> None:
        """POST the resolve-pending call and update result counters."""
        amount_changed = tx.amount != Decimal(str(matched_row["amount"]))
        logger.info(
            "Resolving pending tx %s -> settled %s  desc=%r  "
            "old_amount=%s  new_amount=%s  amount_changed=%s",
            matched_row["id"],
            settle_date,
            tx.raw_description,
            matched_row["amount"],
            tx.amount,
            amount_changed,
        )
        if not dry_run:
            resolve_payload: dict[str, Any] = {
                "posted_date": settle_date.isoformat() + "T00:00:00Z",
            }
            if amount_changed:
                resolve_payload["amount"] = str(tx.amount)
                resolve_payload["amount_currency"] = matched_row.get(
                    "amount_currency", "USD"
                )
            try:
                client.post(
                    f"/api/v1/transactions/{matched_row['id']}/resolve-pending/",
                    resolve_payload,
                )
                result.resolved += 1
                if amount_changed:
                    result.resolved_amount_changed += 1
                # Remove from description index so it isn't double-matched.
                desc_list = pending_by_desc.get(
                    matched_row["raw_description"], []
                )
                if matched_row in desc_list:
                    desc_list.remove(matched_row)
            except Exception as e:
                logger.warning(
                    "Failed to resolve pending tx %s: %s",
                    matched_row["id"],
                    e,
                )
        else:
            result.resolved += 1
            if amount_changed:
                result.resolved_amount_changed += 1

    for tx in settled_txs:
        settle_date = tx.transaction_date  # already a date object from parser

        # Primary match: bank_transaction_id is the same for pending and
        # settled states, so it's a reliable anchor when both sides have it.
        if tx.bank_transaction_id:
            matched = pending_by_bank_id.pop(tx.bank_transaction_id, None)
            if matched:
                _resolve_row(matched, settle_date, tx)
                continue

        # Fallback: match by description + date proximity (±5 days).
        candidates = pending_by_desc.get(tx.raw_description, [])
        if not candidates:
            continue

        close: list[tuple[int, Decimal, dict[str, Any]]] = []
        for row in candidates:
            # posted_date from the API is an ISO datetime string.
            row_date = datetime.fromisoformat(
                row["posted_date"].replace("Z", "+00:00")
            ).date()
            delta = abs((settle_date - row_date).days)
            if delta <= MAX_DATE_DELTA:
                row_amount = Decimal(str(row["amount"]))
                amount_diff = abs(tx.amount - row_amount)
                close.append((delta, amount_diff, row))

        if not close:
            continue

        # Pick closest date; break ties by closest amount.
        close.sort(key=lambda t: (t[0], t[1]))
        _, _, matched_row = close[0]
        # Remove from description index to prevent double-matching.
        pending_by_desc[tx.raw_description].remove(matched_row)
        _resolve_row(matched_row, settle_date, tx)

    return result


########################################################################
########################################################################
#
def _setup_logging(
    verbose: bool, interactive: bool, console: Console | None = None
) -> None:
    """Configure logging based on verbosity and output mode."""
    level = logging.DEBUG if verbose else logging.INFO
    if interactive:
        logging.basicConfig(
            level=level,
            format="%(message)s",
            datefmt="[%X]",
            handlers=[
                RichHandler(
                    console=console,
                    rich_tracebacks=True,
                    show_path=False,
                )
            ],
        )
    else:
        logging.basicConfig(
            level=level,
            format="%(levelname)s %(name)s: %(message)s",
        )
    if not verbose:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("selenium").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)


########################################################################
########################################################################
#
@click.command(
    context_settings={"auto_envvar_prefix": "MIBUDGE"},
    help=(
        "Live-scrape Bank of America and import transactions into mibudge. "
        "Logs in via the bofa_scraper Selenium/Firefox driver, fetches all "
        "accessible accounts, and submits transactions through the same "
        "dedup + POST pipeline as the CSV/OFX importers.\n\n"
        "BofA credentials are read from BOFA_ID and BOFA_PASSCODE env vars "
        "(or --bofa-id / --bofa-passcode).  mibudge credentials follow the "
        "same order as the CSV importer.\n\n"
        "If BofA requires 2FA the scraper prompts for the code via stdin; "
        "run with --no-headless to watch the browser."
    ),
)
@click.option(
    "--bofa-id",
    envvar="BOFA_ID",
    default=None,
    prompt="BofA Online ID",
    help="BofA online ID (env var: BOFA_ID).",
)
@click.option(
    "--bofa-passcode",
    envvar="BOFA_PASSCODE",
    default=None,
    prompt="BofA Passcode",
    hide_input=True,
    help="BofA passcode (env var: BOFA_PASSCODE; prefer env over CLI flag).",
)
@click.option(
    "--url",
    "-u",
    default=None,
    help="Base URL of the mibudge API.  [default: https://localhost:8000]",
)
@click.option("--username", default=None, help="mibudge API username.")
@click.option(
    "--password",
    default=None,
    help="mibudge API password (prefer env var or Vault over CLI flag).",
)
@click.option(
    "--vault-path",
    default=None,
    help="Vault KV2 path for mibudge credentials (e.g. 'mibudge/importer').",
)
@click.option(
    "--ca-bundle",
    default=None,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to a PEM CA bundle to trust (overrides system CAs).",
)
@click.option(
    "--trust-local-certs",
    is_flag=True,
    help=(
        "Trust the mkcert root CA (located via `mkcert -CAROOT`). "
        "Required when connecting to a local dev server using mkcert TLS."
    ),
)
@click.option(
    "--headless/--no-headless",
    default=True,
    show_default=True,
    help="Run Firefox headlessly (default) or visibly for debugging/2FA.",
)
@click.option(
    "--timeout",
    default=5,
    type=float,
    show_default=True,
    help="Selenium page-load timeout in seconds.",
)
@click.option(
    "--account",
    "-a",
    "account_filters",
    multiple=True,
    help=(
        "Filter by BofA account name substring (matches the BofA-side "
        "account name, e.g. 'Checking' or '1234'). Repeatable; when "
        "omitted all accessible accounts are imported."
    ),
)
@click.option(
    "--dry-run",
    "-n",
    is_flag=True,
    help=(
        "Show what would be imported without making any changes. "
        "Scrapes, authenticates, and checks for duplicates, but does "
        "not POST or PATCH any transactions."
    ),
)
@click.option(
    "--run-funding",
    is_flag=True,
    help=(
        "Run the funding engine after each successful account import. "
        "Skipped on --dry-run."
    ),
)
@click.option(
    "--save-dir",
    default=None,
    type=click.Path(file_okay=False, writable=True, path_type=Path),
    help=(
        "Save raw scraped data for each account to a JSON file in this "
        "directory.  Files are named YYYY-MM-DD-HHMMSS-<last4>.json and "
        "can be replayed later with import_bofa_saved.  "
        "[env var: MIBUDGE_SAVE_DIR]"
    ),
)
@click.option(
    "--save-only",
    is_flag=True,
    help=(
        "Scrape and save to --save-dir, then exit without connecting to "
        "mibudge.  Requires --save-dir.  Useful for capturing data on a "
        "machine that can reach BofA but not mibudge, or before deciding "
        "whether to import."
    ),
)
@click.option("--verbose", "-v", is_flag=True, help="Enable DEBUG logging.")
@click.option(
    "--plain",
    is_flag=True,
    help="Disable rich output (auto-disabled when not a TTY).",
)
@theme_option
def cli_cmd(
    bofa_id: str,
    bofa_passcode: str,
    url: str | None,
    username: str | None,
    password: str | None,
    vault_path: str | None,
    ca_bundle: Path | None,
    trust_local_certs: bool,
    headless: bool,
    timeout: float,
    account_filters: tuple[str, ...],
    dry_run: bool,
    run_funding: bool,
    save_dir: Path | None,
    save_only: bool,
    verbose: bool,
    plain: bool,
    theme_name: str,
) -> None:
    """CLI entry point for the live BofA importer."""
    if save_only and save_dir is None:
        raise click.UsageError("--save-only requires --save-dir.")

    console = Console(theme=get_theme(theme_name).rich, stderr=True)
    interactive = console.is_terminal and not plain
    _setup_logging(verbose, interactive, console=console)

    if dry_run and interactive:
        console.print(
            "[bold warning]DRY RUN[/bold warning] — no changes will be made."
        )

    # --- Lazy-import scraper so missing deps fail with a friendly message ---
    try:
        from bofa_scraper import BofAScraper
        from selenium.common.exceptions import (
            NoSuchElementException,
            WebDriverException,
        )
    except ImportError as e:
        raise click.ClickException(
            f"bofa_scraper / selenium are not installed ({e}). "
            "Install the importers-bofa dependency group:\n"
            "  uv sync --group importers-bofa"
        ) from e

    # --- Launch browser ---
    if interactive:
        console.print("[bold]Initializing browser...[/bold]")
    else:
        logger.info("Initializing browser (headless=%s)...", headless)

    try:
        scraper = BofAScraper(
            bofa_id,
            bofa_passcode,
            timeout_duration=timeout,
            headless=headless,
            verbose=verbose,
        )
    except WebDriverException as e:
        raise click.ClickException(f"Failed to launch browser: {e}") from e

    any_error = False
    try:
        # --- Log in to BofA ---
        if interactive:
            console.print("[bold]Logging in to Bank of America...[/bold]")
        else:
            logger.info("Logging in to Bank of America...")

        scraper.login()

        if not scraper.logged_in:
            raise click.ClickException(
                "BofA login failed. Check credentials or run with "
                "--no-headless to inspect the browser state."
            )
        if interactive:
            console.print("[success]Logged in to BofA.[/success]")
        else:
            logger.info("BofA login successful.")

        # --- Collect and filter accounts ---
        accounts = scraper.get_accounts()
        if not accounts:
            raise click.ClickException(
                "No BofA accounts found after login. The page layout may "
                "have changed; run with --no-headless to inspect."
            )

        if account_filters:
            filters_lower = [f.lower() for f in account_filters]
            selected = [
                a
                for a in accounts
                if any(f in a.get_name().lower() for f in filters_lower)
            ]
            if not selected:
                names = [a.get_name() for a in accounts]
                raise click.ClickException(
                    f"No BofA accounts matched filter(s) "
                    f"{list(account_filters)}. "
                    f"Available: {names}."
                )
        else:
            selected = list(accounts)

        if interactive:
            console.print(
                f"[dim]Found {len(accounts)} BofA account(s); "
                f"{'saving' if save_only else 'importing'} "
                f"{len(selected)}.[/dim]"
            )

        # --- Scrape all accounts ---
        # Scraping is separated from importing so --save-only can exit
        # cleanly without ever connecting to mibudge.
        scraped: list[Any] = []
        scrape_time = datetime.now(UTC)
        for account in selected:
            acct_name = account.get_name()
            if interactive:
                console.rule(f"[bold]{acct_name}[/bold]")
            else:
                logger.info("--- Scraping account: %s ---", acct_name)

            try:
                sess = scraper.open_account(account)
                try:
                    sess.scrape_transactions()
                    try:
                        sess.load_more_transactions()
                        sess.scrape_transactions()
                    except NoSuchElementException:
                        pass  # no "load more" button; first scrape got everything
                finally:
                    sess.close()
            except (WebDriverException, Exception) as e:
                if interactive:
                    console.print(
                        f"[error]Failed to scrape {acct_name!r}: {e}[/error]"
                    )
                else:
                    logger.error("Failed to scrape %r: %s", acct_name, e)
                any_error = True
                continue

            txs = account.get_transactions()
            if interactive:
                console.print(f"[dim]Scraped {len(txs)} transaction(s).[/dim]")
            else:
                logger.info("Scraped %d transaction(s).", len(txs))

            if save_dir is not None:
                saved_path = save_scraped_account(
                    account, save_dir, scrape_time
                )
                if interactive:
                    console.print(f"[dim]Saved scrape → {saved_path}[/dim]")
                else:
                    logger.info("Saved scrape to %s", saved_path)

            scraped.append(account)

        if save_only:
            return

        # --- Connect to mibudge and import ---
        with _build_client(
            url=url,
            username=username,
            password=password,
            vault_path=vault_path,
            ca_bundle=ca_bundle,
            trust_local_certs=trust_local_certs,
            console=console,
            interactive=interactive,
        ) as client:
            if interactive:
                with console.status("[bold]Authenticating to mibudge..."):
                    client.authenticate()
                console.print("[success]Authenticated to mibudge.[/success]")
            else:
                client.authenticate()
                logger.info("Authenticated to mibudge.")

            user_timezone: str = client.get("/api/v1/users/me/").get(
                "timezone", "UTC"
            )
            logger.info("User timezone: %s", user_timezone)

            for account in scraped:
                acct_name = account.get_name()
                if interactive:
                    console.rule(f"[bold]{acct_name}[/bold]")
                else:
                    logger.info("--- Importing account: %s ---", acct_name)

                # Build statement
                statement = _build_statement(account)

                # Auto-match mibudge account by last-4-digits substring query
                last_four = _extract_last_four(acct_name)
                if last_four is None:
                    if interactive:
                        console.print(
                            f"[warning]Could not extract last-4 digits from "
                            f"{acct_name!r}; skipping.[/warning]"
                        )
                    else:
                        logger.warning(
                            "Could not extract last-4 from %r; skipping.",
                            acct_name,
                        )
                    any_error = True
                    continue

                try:
                    bank_account_id = _resolve_account_by_query(
                        client,
                        last_four,
                        console=console,
                        interactive=interactive,
                    )
                except click.ClickException as e:
                    if interactive:
                        console.print(
                            f"[warning]Skipping {acct_name!r}: "
                            f"{e.format_message()}[/warning]"
                        )
                    else:
                        logger.warning(
                            "Skipping %r: %s", acct_name, e.format_message()
                        )
                    any_error = True
                    continue

                # Resolve any DB-pending rows whose settled counterparts
                # appear in this scrape.  Must run before _fetch_existing so
                # that the resolved rows appear in the dedup map.
                resolve_result = _resolve_pending_transactions(
                    statement,
                    bank_account_id,
                    client,
                    user_timezone,
                    dry_run=dry_run,
                )
                if resolve_result.resolved:
                    logger.info(
                        "Resolved %d pending transaction(s) "
                        "(%d with amount change).",
                        resolve_result.resolved,
                        resolve_result.resolved_amount_changed,
                    )

                # Pre-fetch dedup window (settled transactions only)
                settled_txs = [
                    tx for tx in statement.transactions if not tx.pending
                ]
                existing: dict[
                    tuple[str, str, str], list[tuple[str, str, str]]
                ] = {}
                existing_by_bank_id: dict[str, tuple[str, str, str]] = {}
                if settled_txs:
                    dedup_start = min(tx.transaction_date for tx in settled_txs)
                    dedup_end = max(tx.transaction_date for tx in settled_txs)
                    if interactive:
                        with console.status(
                            f"[bold]Fetching existing transactions "
                            f"({dedup_start} -> {dedup_end})..."
                        ):
                            existing, existing_by_bank_id = _fetch_existing(
                                client,
                                bank_account_id,
                                dedup_start,
                                dedup_end,
                                user_timezone,
                            )
                    else:
                        existing, existing_by_bank_id = _fetch_existing(
                            client,
                            bank_account_id,
                            dedup_start,
                            dedup_end,
                            user_timezone,
                        )

                # Resolve descriptions that BofA truncated in the web UI
                # (e.g. "...CO...") against their full stored versions so
                # the exact-match dedup catches prior CSV-imported entries.
                if existing:
                    statement = _resolve_truncated_descriptions(
                        statement, existing
                    )

                # Import
                result = import_statement(
                    statement,
                    bank_account_id,
                    client,
                    user_timezone,
                    existing=existing,
                    existing_by_bank_id=existing_by_bank_id,
                    dry_run=dry_run,
                )

                # Per-account summary
                if interactive:
                    verb = "Would import" if dry_run else "Imported"
                    resolve_verb = "Would resolve" if dry_run else "Resolved"
                    update_verb = "Would update" if dry_run else "Updated"
                    title = (
                        f"{'Dry Run ' if dry_run else ''}Summary — {acct_name}"
                    )
                    table = Table(title=title, show_header=False)
                    table.add_column("Metric", style="bold")
                    table.add_column("Count", justify="right")
                    table.add_row(
                        f"{resolve_verb} (pending→posted)",
                        f"[accent]{resolve_result.resolved}[/accent]",
                    )
                    table.add_row(verb, f"[success]{result.imported}[/success]")
                    table.add_row(
                        "Skipped (duplicates)", f"[dim]{result.skipped}[/dim]"
                    )
                    table.add_row(
                        f"{update_verb} (type backfill)",
                        f"[accent]{result.updated}[/accent]",
                    )
                    table.add_row(
                        "Failed",
                        f"[error]{result.failed}[/error]"
                        if result.failed
                        else "0",
                    )
                    console.print()
                    console.print(table)
                    if result.unrecognized:
                        console.print(
                            f"\n[warning]{len(result.unrecognized)} "
                            f"transaction(s) with unrecognized type[/warning]"
                        )
                        seen: set[str] = set()
                        for desc in result.unrecognized:
                            if desc not in seen:
                                seen.add(desc)
                                console.print(f"  [dim]{desc}[/dim]")
                else:
                    prefix = "DRY RUN. " if dry_run else ""
                    verb = "Would import" if dry_run else "Imported"
                    resolve_verb = "Would resolve" if dry_run else "Resolved"
                    update_verb = "Would update" if dry_run else "Updated"
                    print(
                        f"{prefix}{acct_name}: "
                        f"{resolve_verb} {resolve_result.resolved} pending, "
                        f"{verb} {result.imported}, "
                        f"Skipped {result.skipped}, "
                        f"{update_verb} {result.updated}, "
                        f"Failed {result.failed}."
                    )

                if result.failed > 0:
                    any_error = True

                # mark-imported and run-funding only when there are settled
                # transactions to anchor last_posted_through; skipped when the
                # account has only pending transactions (avoids falsely
                # advancing the funding gate).
                if not dry_run and settled_txs:
                    _mark_imported(
                        client,
                        bank_account_id,
                        statement.ending_date,
                        console=console,
                        interactive=interactive,
                    )
                    if run_funding:
                        _run_funding(
                            client,
                            bank_account_id,
                            console=console,
                            interactive=interactive,
                        )

                # Post-import balance check: after all transactions are
                # posted, mibudge's available_balance should match BofA's
                # ending (available) balance.  A mismatch after import
                # suggests transactions exist in BofA's history that
                # aren't in the scrape window (e.g. older than the
                # activity page) or were never imported.
                if not dry_run:
                    updated = client.get(
                        f"/api/v1/bank-accounts/{bank_account_id}/"
                    )
                    mibudge_bal = Decimal(
                        str(updated["available_balance"])
                    ).quantize(Decimal("0.01"))
                    bofa_bal = statement.ending_balance
                    bal_diff = bofa_bal - mibudge_bal
                    if bal_diff != Decimal("0.00"):
                        bal_msg = (
                            f"Post-import balance mismatch for "
                            f"{acct_name!r}: BofA={bofa_bal}, "
                            f"mibudge={mibudge_bal} "
                            f"(off by {bal_diff:+.2f}) -- "
                            f"possible transactions outside the scraped "
                            f"window or never imported."
                        )
                        if interactive:
                            console.print(f"[warning]{bal_msg}[/warning]")
                        else:
                            logger.warning(bal_msg)
                        any_error = True
                    else:
                        if interactive:
                            console.print(
                                f"[success]Balance verified: "
                                f"{bofa_bal}[/success]"
                            )
                        else:
                            logger.info(
                                "Post-import balance verified: %s", bofa_bal
                            )

    except AuthenticationError as e:
        raise click.ClickException(str(e)) from e
    except KeyboardInterrupt as e:
        raise click.Abort() from e
    finally:
        scraper.quit()

    if any_error:
        raise SystemExit(1)


########################################################################
########################################################################
#
def cli() -> None:
    """Load .env and invoke the CLI."""
    load_dotenv()
    cli_cmd()


if __name__ == "__main__":
    cli()
