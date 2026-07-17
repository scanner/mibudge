"""
Import live Bank of America transactions into mibudge via its REST API.

Logs into Bank of America using the bofa_scraper Selenium/Firefox
scraper, scrapes all accessible accounts, and POSTs each scrape to
mibudge's scrape-sync endpoint
(`POST /api/v1/bank-accounts/{id}/sync-scrape/`).  The server handles
pending wipe-and-reinsert, posted-row dedup, snapshot recomputation,
and balance validation atomically.

Requires the importers-bofa optional dependency group::

    uv sync --group importers-bofa
    uv run --group importers-bofa python -m importers.import_bofa_live

BofA credentials are read from BOFA_ID and BOFA_PASSCODE environment
variables or the --bofa-id / --bofa-passcode flags.  Alternatively,
set BOFA_ONEPASSWORD_URL (or --bofa-onepassword-url) to an `op://`
item URL and credentials are fetched via `op read` -- useful in
automated contexts where plaintext env vars are undesirable.  mibudge
credentials follow the same resolution order as the CSV importer (CLI
flags > env vars > .env > the MIBUDGE_API_KEY_ONEPASSWORD_URL secret
reference > Vault).  The two 1Password URLs are deliberately separate
env vars -- BOFA_ONEPASSWORD_URL is an *item* URL for the bank login
(username/password fields are read from it), while
MIBUDGE_API_KEY_ONEPASSWORD_URL is a full secret reference (item plus
field path) to the API key used to authenticate to mibudge -- so each
secret's name says what it unlocks.

2FA: if BofA requires it, the scraper prompts for the code
interactively via stdin.  Run with --no-headless to watch the browser.

Scraper-output notes (verified against all four accounts via
~/src/bank_project/bofa_test/bofa_test.py on 2026-05-13):

* Amount signs are correct -- BofA renders debits as `-$xx.xx` in the
  amount-cell so the scraped floats are already negative for debits.
* Pending transactions show `Processing` in the date-cell instead of
  a parseable date.  `_parse_scraped_date` treats any unparseable
  date string as pending, which keeps the importer tolerant of other
  banks' markers if we ever wire one up here.
* Account names follow the pattern `NAME - XXXX` where XXXX is the
  last 4 digits used to match the mibudge BankAccount.

Details enrichment: after each account's sync-scrape POST, the server
returns `details_needed` -- the posted rows (by submitted-array index
and transaction UUID) whose DB row has never been enriched.  While the
scrape session is still open (bofa_scraper txn hashes are
session-scoped), the importer fetches BofA's per-transaction details
for those rows and POSTs them to the transaction-details endpoint.
Fetches are paced and budgeted run-wide (--details-limit, default 30
dialog opens; the BofA burst limit wedges the page at ~40-50 opens per
login session) and each merchant is fetched only once per run --
repeat rows get a merchant-copy synthesized at zero dialog cost (see
importers/bofa_common.py).  Rows left unfetched stay details-NULL
server-side and are re-reported by the next run's sync, so a backfill
converges over successive runs.
"""

# system imports
import json
import logging
import re
import subprocess
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

# 3rd party imports
import click
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

# Project imports
from importers.bofa_common import (
    DEFAULT_DETAILS_LIMIT,
    BofASessionLost,
    DetailsPacer,
    fetch_details_for_account,
    normalize_description,
)
from importers.client import AuthenticationError
from importers.import_transactions import (
    _build_client,
    _resolve_account_by_query,
    _run_funding,
    load_importer_env,
)
from importers.parsers.bofa_csv import _infer_transaction_type
from importers.theme import get_theme, theme_option

logger = logging.getLogger(__name__)

SCRAPE_FORMAT_VERSION = 3


########################################################################
########################################################################
#
def _read_bofa_credentials_from_1password(base_url: str) -> tuple[str, str]:
    """Fetch BofA credentials from the 1Password CLI.

    This reads the BofA login item (BOFA_ONEPASSWORD_URL /
    --bofa-onepassword-url) -- distinct from the mibudge API-key
    secret reference read by `_resolve_api_key_from_1password` in
    import_transactions.py (MIBUDGE_API_KEY_ONEPASSWORD_URL /
    --api-key-onepassword-url).

    Strips any trailing slash from `base_url` before appending the
    field names, so both `op://vault/item` and `op://vault/item/`
    work correctly.

    Args:
        base_url: 1Password item URL (e.g. `op://Personal/BofA`).

    Returns:
        A ``(username, password)`` tuple.

    Raises:
        click.ClickException: If the ``op`` CLI is not found or returns
            a non-zero exit code.
    """
    url = base_url.rstrip("/")
    try:
        username = subprocess.run(
            ["op", "read", f"{url}/username"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        password = subprocess.run(
            ["op", "read", f"{url}/password"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except FileNotFoundError as e:
        raise click.ClickException(
            "1Password CLI (op) not found in PATH. "
            "Install it from https://1password.com/downloads/command-line/"
        ) from e
    except subprocess.CalledProcessError as e:
        raise click.ClickException(
            f"Failed to read credentials from 1Password "
            f"({url!r}): {e.stderr.strip()}"
        ) from e
    return username, password


########################################################################
########################################################################
#
@dataclass
class SavedTransaction:
    """One transaction as scraped from the BofA activity table.

    Field names match what bofa_scraper's transaction objects expose so
    that a list of these can be fed straight to the payload builder via
    `_ReplayAccount`.  `date` is the raw BofA string -- e.g.
    `'05/07/2026'` for settled transactions and `'Processing'` for
    pending ones.

    `txn_hash` is captured from the scraper for reference but is not
    used: it changes on every scrape, so it is not a stable dedup key.
    Empty string for files saved before format_version 2.

    `running_balance` is the available balance after this transaction
    as shown in BofA's activity table.  Passed through to the server
    for the posting-order sanity walk.  `'0.00'` for files saved before
    format_version 2.

    `details` is the raw per-transaction details dict fetched from the
    View/Edit dialog, when the live run captured one (format_version 3);
    None otherwise.  Replayed through the transaction-details endpoint
    by import_bofa_saved.
    """

    date: str
    desc: str
    amount: str
    type: str
    txn_hash: str = ""
    running_balance: str = "0.00"
    details: dict[str, Any] | None = None


########################################################################
########################################################################
#
@dataclass
class SavedScrape:
    """Complete scrape result for one BofA account.

    Stores the raw scraped fields verbatim so that `import_bofa_saved`
    can replay the file through the scrape-sync endpoint and produce
    identical server-side state to the original live run.
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
    details_by_index: dict[int, dict[str, Any]] | None = None,
) -> Path:
    """Serialize a scraped BofA account to a JSON file.

    Args:
        account: bofa_scraper Account with transactions populated.
        save_dir: Directory to write the file into.
        scraped_at: Timestamp of the scrape (UTC).
        details_by_index: Fetched per-transaction details keyed by the
            transaction's index in `account.get_transactions()`.
            Attached to the saved rows so import_bofa_saved can replay
            the enrichment.

    Returns:
        Path to the written file.
    """
    last_four = _extract_last_four(account.get_name()) or "xxxx"
    ts = scraped_at.strftime("%Y-%m-%d-%H%M%S")
    filename = save_dir / f"{ts}-{last_four}.json"

    details_by_index = details_by_index or {}
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
                details=details_by_index.get(i),
            )
            for i, tx in enumerate(raw_txs)
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
    if version not in (1, 2, SCRAPE_FORMAT_VERSION):
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
            # `details` was added (optional) in format_version 3; the
            # dataclass default covers v2 rows.
            txs.append(SavedTransaction(**tx))
    return SavedScrape(
        format_version=version,
        scraped_at=data["scraped_at"],
        account_name=data["account_name"],
        ending_balance=data["ending_balance"],
        transactions=txs,
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


########################################################################
########################################################################
#
def _build_sync_payload(
    account: Any, scraped_at: datetime, user_timezone: str
) -> tuple[dict[str, Any], int, int]:
    """Convert a scraped account into a sync-scrape POST body.

    Iterates `account.get_transactions()` in its native (newest-first)
    order and emits a JSON-ready payload matching
    `ScrapeSyncSerializer` on the mibudge side.  The server takes
    over from here -- pending detection from `is_pending`, dedup of
    posted rows, snapshot recomputation, balance verification.

    `posted_date` values are anchored to midnight in `user_timezone`
    so they line up with the convention used by the CSV / OFX
    importers (see `import_transactions._post_transaction`).  The bank
    only gives us a bare MM/DD/YYYY with no timezone tag; the codebase
    treats that as a calendar date in the user's timezone.

    TODO: verify this assumption by running the scraper with
    `--save-only` from a host configured to a different timezone (or
    with the browser's timezone overridden) and comparing the date
    column to a control run from the user's home timezone.  If BofA's
    JS converts dates client-side, we'd see them shift.  If not, the
    date column is bank-side and our user-tz-midnight anchor is just a
    pragmatic convention.

    Args:
        account: A `bofa_scraper.Account` (or `_ReplayAccount`) whose
            `get_transactions()` returns objects with `.date`,
            `.desc`, `.amount`, `.type`, and optionally
            `.running_balance`.
        scraped_at: Wall-clock UTC datetime of the scrape.
        user_timezone: IANA timezone name for the account owner
            (e.g. 'America/Los_Angeles').

    Returns:
        A `(payload, posted_count, pending_count)` tuple.  The counts
        are reported in the CLI summary so the user sees what was
        scraped without waiting on the server.
    """
    tz = ZoneInfo(user_timezone)
    raw_txs = account.get_transactions()
    transactions: list[dict[str, Any]] = []
    posted_count = 0
    pending_count = 0

    # Pending rows do not have a settled date yet (BofA shows
    # 'Processing' in the date column; other banks may use other
    # markers), so substitute the scrape's wall-clock -- in the user's
    # tz -- as the placeholder posted_date.  The server derives
    # transaction_date from the embedded MM/DD in the description,
    # falling back to this value only when no MM/DD is present.
    pending_posted_date = scraped_at.astimezone(tz)

    for tx in raw_txs:
        parsed_date, is_pending = _parse_scraped_date(tx.date)
        amount = Decimal(str(tx.amount)).quantize(Decimal("0.01"))
        raw_description = normalize_description(tx.desc)
        transaction_type = _infer_transaction_type(raw_description, amount)

        if is_pending:
            posted_dt = pending_posted_date
            pending_count += 1
        else:
            posted_dt = datetime(
                parsed_date.year,
                parsed_date.month,
                parsed_date.day,
                tzinfo=tz,
            )
            posted_count += 1

        running_balance = getattr(tx, "running_balance", None)
        running_balance_out: str | None = None
        if running_balance is not None:
            try:
                rb = Decimal(str(running_balance)).quantize(Decimal("0.01"))
                if rb != Decimal("0.00"):
                    running_balance_out = str(rb)
            except Exception:
                pass

        transactions.append(
            {
                "is_pending": is_pending,
                "posted_date": posted_dt.isoformat(),
                "raw_description": raw_description,
                "amount": str(amount),
                "amount_currency": "USD",
                "transaction_type": transaction_type,
                "running_balance": running_balance_out,
            }
        )

    ending_balance = Decimal(str(account.get_balance())).quantize(
        Decimal("0.01")
    )
    payload: dict[str, Any] = {
        "scraped_at": scraped_at.isoformat(),
        "ending_balance": str(ending_balance),
        "ending_balance_currency": "USD",
        "transactions": transactions,
    }
    return payload, posted_count, pending_count


########################################################################
########################################################################
#
def _post_sync_scrape(
    client: Any,
    bank_account_id: str,
    payload: dict[str, Any],
    posted_count: int,
    pending_count: int,
    account_label: str,
    dry_run: bool,
    console: Console,
    interactive: bool,
) -> tuple[bool, dict[str, Any] | None]:
    """POST the scrape to mibudge and render the result.

    Args:
        client: Authenticated `MibudgeClient`.
        bank_account_id: UUID string of the mibudge BankAccount.
        payload: Body built by `_build_sync_payload`.
        posted_count: Number of settled rows in the payload (for the
            summary, in case the server skips a few as duplicates).
        pending_count: Number of pending rows in the payload.
        account_label: Display label for the account.
        dry_run: When true, print the would-send summary and do not
            POST.
        console: Rich console for interactive output.
        interactive: Whether to render via Rich tables.

    Returns:
        An ``(ok, report)`` tuple.  `ok` is True on success (including
        dry-run) and False if the POST raised or the server reported a
        balance mismatch / posting-order warning.  `report` is the
        server's ScrapeSyncReport dict (carrying `details_needed`), or
        None on dry-run / POST failure.
    """
    if dry_run:
        msg = (
            f"DRY RUN. {account_label}: would sync "
            f"{posted_count} posted, {pending_count} pending."
        )
        if interactive:
            console.print(f"[warning]{msg}[/warning]")
        else:
            print(msg)
        return True, None

    try:
        report = client.post(
            f"/api/v1/bank-accounts/{bank_account_id}/sync-scrape/",
            payload,
        )
    except Exception as exc:
        if interactive:
            console.print(
                f"[error]sync-scrape failed for {account_label}: {exc}[/error]"
            )
        else:
            logger.error("sync-scrape failed for %s: %s", account_label, exc)
        return False, None

    # DRF serializes DecimalField as a string -- coerce so we can apply
    # signed numeric formatting.  None means the totals matched.
    raw_mismatch = report.get("balance_mismatch")
    balance_mismatch: Decimal | None = (
        Decimal(raw_mismatch) if raw_mismatch is not None else None
    )
    posting_warnings = report.get("posting_order_mismatches") or []
    ok = balance_mismatch is None and not posting_warnings

    if interactive:
        table = Table(title=f"Summary -- {account_label}", show_header=False)
        table.add_column("Metric", style="bold")
        table.add_column("Value", justify="right")
        table.add_row(
            "Deleted pending", f"[accent]{report['deleted_pending']}[/accent]"
        )
        table.add_row(
            "Inserted posted", f"[success]{report['inserted_posted']}[/success]"
        )
        table.add_row(
            "Skipped posted (already in DB)",
            f"[dim]{report['skipped_posted']}[/dim]",
        )
        table.add_row(
            "Inserted pending",
            f"[success]{report['inserted_pending']}[/success]",
        )
        bal_str = (
            f"[error]{balance_mismatch:+}[/error]"
            if balance_mismatch is not None
            else "[success]match[/success]"
        )
        table.add_row("Ending balance", bal_str)
        last_through = report.get("last_posted_through") or "-"
        table.add_row("last_posted_through", str(last_through))
        table.add_row(
            "Details needed",
            f"[accent]{len(report.get('details_needed') or [])}[/accent]",
        )
        console.print()
        console.print(table)
        for w in posting_warnings:
            console.print(f"[warning]posting-order: {w}[/warning]")
    else:
        bal_str = (
            f"mismatch={balance_mismatch:+}"
            if balance_mismatch is not None
            else "balance OK"
        )
        print(
            f"{account_label}: "
            f"deleted_pending={report['deleted_pending']}, "
            f"inserted_posted={report['inserted_posted']}, "
            f"skipped_posted={report['skipped_posted']}, "
            f"inserted_pending={report['inserted_pending']}, "
            f"details_needed={len(report.get('details_needed') or [])}, "
            f"{bal_str}."
        )
        for w in posting_warnings:
            logger.warning("posting-order: %s", w)

    return ok, report


########################################################################
########################################################################
#
def _post_transaction_details(
    client: Any,
    bank_account_id: str,
    items: list[dict[str, Any]],
    account_label: str,
    console: Console,
    interactive: bool,
) -> bool:
    """POST fetched transaction details to mibudge and render the result.

    Args:
        client: Authenticated `MibudgeClient`.
        bank_account_id: UUID string of the mibudge BankAccount.
        items: ``{"transaction": uuid, "details": dict}`` entries from
            `fetch_details_for_account` (or a saved-scrape replay).
        account_label: Display label for the account.
        console: Rich console for interactive output.
        interactive: Whether to render via Rich.

    Returns:
        True when the POST succeeded (individual skips are reported
        but do not fail the run); False when it raised.
    """
    try:
        report = client.post(
            f"/api/v1/bank-accounts/{bank_account_id}/transaction-details/",
            {"details": items},
        )
    except Exception as exc:
        if interactive:
            console.print(
                f"[error]transaction-details failed for "
                f"{account_label}: {exc}[/error]"
            )
        else:
            logger.error(
                "transaction-details failed for %s: %s", account_label, exc
            )
        return False

    summary = (
        f"details applied={report['applied']}, "
        f"skipped_has_details={report['skipped_has_details']}, "
        f"skipped_pending={report['skipped_pending']}, "
        f"not_found={report['not_found']}"
    )
    if interactive:
        console.print(f"[dim]{account_label}: {summary}[/dim]")
    else:
        logger.info("%s: %s", account_label, summary)

    for result in report.get("results", []):
        for warning in result.get("warnings", []):
            logger.warning(
                "%s: details %s: %s",
                account_label,
                result.get("transaction"),
                warning,
            )
    return True


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
    help="BofA online ID (env var: BOFA_ID).",
)
@click.option(
    "--bofa-passcode",
    envvar="BOFA_PASSCODE",
    default=None,
    help="BofA passcode (env var: BOFA_PASSCODE; prefer env over CLI flag).",
)
@click.option(
    "--bofa-onepassword-url",
    envvar="BOFA_ONEPASSWORD_URL",
    default=None,
    help=(
        "1Password item URL to source BofA credentials from "
        "(e.g. 'op://Personal/BofA').  When set, the CLI calls "
        "`op read <url>/username` and `op read <url>/password` "
        "instead of reading BOFA_ID / BOFA_PASSCODE.  "
        "Env var: BOFA_ONEPASSWORD_URL. Distinct from "
        "--api-key-onepassword-url, which sources the mibudge API key."
    ),
)
@click.option(
    "--url",
    "-u",
    default=None,
    help="Base URL of the mibudge API.  [default: https://localhost:8000]",
)
@click.option("--email", default=None, help="mibudge API login email.")
@click.option(
    "--password",
    default=None,
    help="mibudge API password (prefer env var or Vault over CLI flag).",
)
@click.option(
    "--api-key",
    default=None,
    help=(
        "mibudge API key (preferred over email/password; prefer env var "
        "MIBUDGE_API_KEY or Vault over CLI flag)."
    ),
)
@click.option(
    "--vault-path",
    default=None,
    help="Vault KV2 path for mibudge credentials (e.g. 'mibudge/importer').",
)
@click.option(
    "--api-key-onepassword-url",
    default=None,
    help=(
        "1Password secret reference to the API key used to "
        "authenticate to mibudge -- the full field path "
        "'op://<vault>/<item>[/<section>]/<field>', e.g. "
        "'op://Personal/mibudge/API key'. Used when --api-key is not "
        "given. Env var: MIBUDGE_API_KEY_ONEPASSWORD_URL. Distinct "
        "from --bofa-onepassword-url, an item URL sourcing BofA "
        "login credentials."
    ),
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
@click.option(
    "--details-limit",
    default=DEFAULT_DETAILS_LIMIT,
    show_default=True,
    type=int,
    help=(
        "Max transaction-detail dialog opens per RUN across all "
        "accounts (merchant-copies are free).  BofA's burst limit "
        "wedges the page after ~40-50 opens in one login session; "
        "keep this comfortably below that.  0 disables detail "
        "fetching entirely."
    ),
)
@click.option(
    "--details-all",
    is_flag=True,
    help=(
        "With --save-only: fetch the real details dialog for EVERY "
        "posted transaction that has one (paced, unlimited budget, no "
        "merchant-copy shortcut) so the saved file captures the full "
        "data.  Ignores --details-limit.  Expect wedge-recovery "
        "pauses on large histories."
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
    bofa_id: str | None,
    bofa_passcode: str | None,
    bofa_onepassword_url: str | None,
    url: str | None,
    email: str | None,
    password: str | None,
    api_key: str | None,
    vault_path: str | None,
    api_key_onepassword_url: str | None,
    ca_bundle: Path | None,
    trust_local_certs: bool,
    headless: bool,
    timeout: float,
    account_filters: tuple[str, ...],
    dry_run: bool,
    run_funding: bool,
    save_dir: Path | None,
    save_only: bool,
    details_limit: int,
    details_all: bool,
    verbose: bool,
    plain: bool,
    theme_name: str,
) -> None:
    """CLI entry point for the live BofA importer."""
    if save_only and save_dir is None:
        raise click.UsageError("--save-only requires --save-dir.")
    if details_all and not save_only:
        raise click.UsageError(
            "--details-all only applies to --save-only offline captures."
        )

    if bofa_onepassword_url is not None:
        bofa_id, bofa_passcode = _read_bofa_credentials_from_1password(
            bofa_onepassword_url
        )
    else:
        if bofa_id is None:
            bofa_id = click.prompt("BofA Online ID")
        if bofa_passcode is None:
            bofa_passcode = click.prompt("BofA Passcode", hide_input=True)

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

    any_error = False
    session_lost = False

    # One pacer for the whole run -- the BofA burst limit belongs to
    # the login session, not to an individual account page.
    # --details-all offline captures are unlimited (limit -1).
    pacer = DetailsPacer(limit=-1 if details_all else details_limit)
    seen_by_signature: dict[str, tuple[dict[str, Any], str]] = {}

    try:
        with ExitStack() as stack:
            # --- Authenticate to mibudge FIRST ---
            # Fail fast before opening a browser and burning a BofA
            # login (and possibly a 2FA prompt) on a run that could
            # never import.
            client: Any = None
            user_timezone = "UTC"
            if not save_only:
                client = stack.enter_context(
                    _build_client(
                        url=url,
                        email=email,
                        password=password,
                        api_key=api_key,
                        vault_path=vault_path,
                        api_key_onepassword_url=api_key_onepassword_url,
                        ca_bundle=ca_bundle,
                        trust_local_certs=trust_local_certs,
                        console=console,
                        interactive=interactive,
                    )
                )
                if interactive:
                    with console.status("[bold]Authenticating to mibudge..."):
                        client.authenticate()
                    console.print(
                        "[success]Authenticated to mibudge.[/success]"
                    )
                else:
                    client.authenticate()
                    logger.info("Authenticated to mibudge.")

                user_timezone = client.get("/api/v1/users/me/").get(
                    "timezone", "UTC"
                )
                logger.info("User timezone: %s", user_timezone)

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
                raise click.ClickException(
                    f"Failed to launch browser: {e}"
                ) from e
            stack.callback(scraper.quit)

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
                    "No BofA accounts found after login. The page layout "
                    "may have changed; run with --no-headless to inspect."
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

            # --- Per account: scrape -> sync -> fetch details -> post ---
            # The scrape session stays OPEN through the details fetch:
            # bofa_scraper txn hashes are session-scoped, so details
            # can only be fetched while the account page is still live.
            scrape_time = datetime.now(UTC)
            for account in selected:
                acct_name = account.get_name()

                if session_lost:
                    logger.warning(
                        "BofA session lost; skipping remaining account(s) "
                        "starting with %r.",
                        acct_name,
                    )
                    any_error = True
                    break

                if interactive:
                    console.rule(f"[bold]{acct_name}[/bold]")
                else:
                    logger.info("--- Processing account: %s ---", acct_name)

                # Resolve the mibudge account BEFORE scraping so an
                # unmatched account is skipped without page work.
                bank_account_id = ""
                if not save_only:
                    last_four = _extract_last_four(acct_name)
                    if last_four is None:
                        if interactive:
                            console.print(
                                f"[warning]Could not extract last-4 digits "
                                f"from {acct_name!r}; skipping.[/warning]"
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
                                "Skipping %r: %s",
                                acct_name,
                                e.format_message(),
                            )
                        any_error = True
                        continue

                # --- Scrape (session stays open for detail fetches) ---
                details_items: list[dict[str, Any]] = []
                details_by_index: dict[int, dict[str, Any]] = {}
                posted_count = 0
                load_more_clicks = 0
                try:
                    sess = scraper.open_account(account)
                except (WebDriverException, Exception) as e:
                    if interactive:
                        console.print(
                            f"[error]Failed to open {acct_name!r}: {e}[/error]"
                        )
                    else:
                        logger.error("Failed to open %r: %s", acct_name, e)
                    any_error = True
                    continue

                try:
                    try:
                        sess.scrape_transactions()
                        try:
                            sess.load_more_transactions()
                            load_more_clicks = 1
                            sess.scrape_transactions()
                        except NoSuchElementException:
                            # no "load more" button; first scrape got
                            # everything
                            pass
                    except (WebDriverException, Exception) as e:
                        if interactive:
                            console.print(
                                f"[error]Failed to scrape {acct_name!r}: "
                                f"{e}[/error]"
                            )
                        else:
                            logger.error(
                                "Failed to scrape %r: %s", acct_name, e
                            )
                        any_error = True
                        continue

                    raw_txs = account.get_transactions()
                    if interactive:
                        console.print(
                            f"[dim]Scraped {len(raw_txs)} transaction(s).[/dim]"
                        )
                    else:
                        logger.info("Scraped %d transaction(s).", len(raw_txs))

                    if save_only:
                        if details_all:
                            # Offline capture: fetch the real dialog
                            # for every posted row that has one.  Row
                            # ids are list indexes -- there is no
                            # server transaction to reference.
                            capture = [
                                (str(i), tx) for i, tx in enumerate(raw_txs)
                            ]
                            try:
                                results, stats = fetch_details_for_account(
                                    sess,
                                    account,
                                    capture,
                                    pacer,
                                    seen_by_signature,
                                    load_more_clicks,
                                    copy_repeats=False,
                                )
                            except BofASessionLost as exc:
                                results = list(
                                    getattr(exc, "partial_results", [])
                                )
                                session_lost = True
                                logger.warning("%s", exc)
                            details_by_index = {
                                int(item["transaction"]): item["details"]
                                for item in results
                            }
                            logger.info(
                                "%s: captured details for %d transaction(s).",
                                acct_name,
                                len(details_by_index),
                            )
                    else:
                        payload, posted_count, pending_count = (
                            _build_sync_payload(
                                account, scrape_time, user_timezone
                            )
                        )
                        ok, report = _post_sync_scrape(
                            client,
                            bank_account_id,
                            payload,
                            posted_count=posted_count,
                            pending_count=pending_count,
                            account_label=acct_name,
                            dry_run=dry_run,
                            console=console,
                            interactive=interactive,
                        )
                        if not ok:
                            any_error = True

                        # --- Fetch details for rows the server wants ---
                        if report is not None and pacer.limit != 0:
                            needed: list[tuple[str, Any]] = []
                            uuid_to_index: dict[str, int] = {}
                            for row in report.get("details_needed", []):
                                idx = row["index"]
                                tid = row["transaction"]
                                if 0 <= idx < len(raw_txs):
                                    needed.append((tid, raw_txs[idx]))
                                    uuid_to_index.setdefault(tid, idx)

                            if needed:
                                if interactive:
                                    console.print(
                                        f"[dim]Fetching details for "
                                        f"{len(needed)} transaction(s) "
                                        f"(budget left: "
                                        f"{pacer.limit - pacer.used})"
                                        f"...[/dim]"
                                    )
                                stats = None
                                try:
                                    details_items, stats = (
                                        fetch_details_for_account(
                                            sess,
                                            account,
                                            needed,
                                            pacer,
                                            seen_by_signature,
                                            load_more_clicks,
                                        )
                                    )
                                except BofASessionLost as exc:
                                    details_items = list(
                                        getattr(exc, "partial_results", [])
                                    )
                                    session_lost = True
                                    logger.warning("%s", exc)
                                if stats is not None:
                                    msg = (
                                        f"details: fetched={stats.fetched}, "
                                        f"copied={stats.copied}, "
                                        f"failed={stats.failed}, "
                                        f"left-for-next-run="
                                        f"{stats.skipped_budget}"
                                    )
                                    if interactive:
                                        console.print(f"[dim]{msg}[/dim]")
                                    else:
                                        logger.info("%s: %s", acct_name, msg)

                                details_by_index = {
                                    uuid_to_index[item["transaction"]]: item[
                                        "details"
                                    ]
                                    for item in details_items
                                    if item["transaction"] in uuid_to_index
                                }
                finally:
                    sess.close()

                # --- Save (now including any fetched details) ---
                if save_dir is not None:
                    saved_path = save_scraped_account(
                        account, save_dir, scrape_time, details_by_index
                    )
                    if interactive:
                        console.print(f"[dim]Saved scrape → {saved_path}[/dim]")
                    else:
                        logger.info("Saved scrape to %s", saved_path)

                if save_only:
                    continue

                # --- POST fetched details ---
                if details_items:
                    if not _post_transaction_details(
                        client,
                        bank_account_id,
                        details_items,
                        acct_name,
                        console,
                        interactive,
                    ):
                        any_error = True

                # run-funding only fires when at least one settled
                # transaction was in this scrape (pending-only scrapes
                # do not advance last_posted_through and should not
                # trigger funding).
                if not dry_run and run_funding and posted_count > 0:
                    _run_funding(
                        client,
                        bank_account_id,
                        console=console,
                        interactive=interactive,
                    )

    except AuthenticationError as e:
        raise click.ClickException(str(e)) from e
    except KeyboardInterrupt as e:
        raise click.Abort() from e

    if session_lost:
        logger.warning(
            "BofA terminated the login session mid-run; unfetched details "
            "stay pending server-side and will be retried next run."
        )
    if any_error:
        raise SystemExit(1)


########################################################################
########################################################################
#
def cli() -> None:
    """Load importer env vars from .env and invoke the CLI."""
    load_importer_env()
    cli_cmd()


if __name__ == "__main__":
    cli()
