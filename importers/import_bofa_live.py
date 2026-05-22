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
variables or the --bofa-id / --bofa-passcode flags.  mibudge
credentials follow the same resolution order as the CSV importer (CLI
flags > env vars > .env > Vault).

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
from zoneinfo import ZoneInfo

# 3rd party imports
import click
from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

# Project imports
from importers.client import AuthenticationError
from importers.import_transactions import (
    _build_client,
    _resolve_account_by_query,
    _run_funding,
)
from importers.parsers.bofa_csv import _infer_transaction_type
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
    """Collapse internal whitespace to match CSV-imported raw_description values.

    BofA appends extra text after a <br> tag (rendered as \\n by the
    scraper) for some pending transactions, e.g. "Amount may change -
    waiting for final amount from merchant".  Everything from the first
    \\n onwards is UI noise, not part of the transaction description.
    """
    text = text.split("\n")[0]
    return " ".join(text.split())


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
        raw_description = _normalize_description(tx.desc)
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
) -> bool:
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
        True on success (including dry-run); False if the POST raised
        or the server reported a balance mismatch / posting-order
        warning.
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
        return True

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
        return False

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
            f"{bal_str}."
        )
        for w in posting_warnings:
            logger.warning("posting-order: %s", w)

    return ok


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
@click.option("--email", default=None, help="mibudge API login email.")
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
    email: str | None,
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
            email=email,
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

                # Auto-match mibudge account by last-4-digits substring query.
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

                payload, posted_count, pending_count = _build_sync_payload(
                    account, scrape_time, user_timezone
                )
                ok = _post_sync_scrape(
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

                # run-funding only fires when at least one settled
                # transaction was in this scrape (pending-only scrapes do
                # not advance last_posted_through and should not trigger
                # funding).
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
