"""
Import bank-statement files into mibudge via its REST API.

Supported formats:

* ``.csv``                 -- Bank of America CSV export
* ``.ofx`` / ``.qfx``      -- OFX / QFX statements (any FI)

Files are dispatched to a parser module based on extension. For CSVs
from other institutions that happen to use ``.csv`` we can add an
explicit ``--parser`` override later -- OFX is a real spec and one
parser handles everything, while CSVs are per-bank and their file
extension alone cannot discriminate.

Typical usage::

    # Import a pile of OFX files for an already-created account. The
    # OFX ACCTID is matched against BankAccount.account_number, so no
    # --account flag is needed:
    uv run python -m importers import statements/*.ofx

    # First-time import from OFX -- the account type and account
    # number come from the OFX file itself, only --name and --bank
    # are still required.  --bank accepts a name, routing number, or
    # UUID; if the string matches exactly one bank it is used,
    # otherwise all matches (or all banks) are printed:
    uv run python -m importers import --create-account \\
        --name "Personal Card" --bank Chase \\
        statements/*.ofx

    # BofA CSV (no ACCTID in the file) -- --account accepts a name,
    # account number, or UUID:
    uv run python -m importers import -f stmt.csv --account "Personal Checking"

Configuration is resolved in this order (first wins):

    1. CLI flags
    2. Environment variables (MIBUDGE_URL, MIBUDGE_USERNAME, etc.)
    3. .env file (loaded automatically via python-dotenv)
    4. Vault KV2 secret (if --vault-path / MIBUDGE_VAULT_PATH is set)

The Vault secret is expected to contain keys: ``url``, ``username``,
``password``.  Standard Vault env vars (VAULT_ADDR, VAULT_TOKEN) are
used to connect to Vault.
"""

# system imports
import logging
from collections.abc import Callable
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
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

# Project imports
from importers.client import APIError, AuthenticationError, MibudgeClient
from importers.parsers import bofa_csv, ofx
from importers.parsers.common import ParsedStatement, ParsedTransaction
from importers.theme import get_theme, theme_option

logger = logging.getLogger(__name__)

# The server caps at 500; request the maximum to minimize round-trips
# during dedup.
_DEDUP_PAGE_SIZE = 500

# Friendly --account-type choice values mapped to BankAccount.BankAccountType
# codes used by the model / serializer.
_ACCOUNT_TYPE_CHOICES: dict[str, str] = {
    "checking": "C",
    "savings": "S",
    "credit": "X",
}


########################################################################
########################################################################
#
def _fuzzy_match_bank(
    banks: list[dict[str, Any]], query: str
) -> list[dict[str, Any]]:
    """
    Return banks whose name, routing_number, or UUID id contain ``query``.

    Matching is case-insensitive on name, exact substring on the other
    fields.

    Args:
        banks: List of bank dicts from the API.
        query: The user-supplied search string.

    Returns:
        List of matching bank dicts.
    """
    q = query.lower()
    matches: list[dict[str, Any]] = []
    for bank in banks:
        if (
            q in (bank.get("name") or "").lower()
            or q in (bank.get("routing_number") or "")
            or q in (bank.get("id") or "")
        ):
            matches.append(bank)
    return matches


####################################################################
#
def _resolve_bank_by_query(
    client: MibudgeClient,
    query: str,
    *,
    console: Console,
    interactive: bool,
) -> str:
    """
    Fuzzy-match ``query`` against banks and return the UUID.

    If exactly one bank matches, return its ``id``. Otherwise print a
    table of matches (or all banks if none matched) and raise a
    :class:`click.ClickException`.

    Args:
        client:      Authenticated MibudgeClient.
        query:       User-supplied search string.
        console:     Rich console for output.
        interactive: Whether to use rich formatting.

    Returns:
        The matched bank's UUID.

    Raises:
        click.ClickException: On zero or multiple matches.
    """
    all_banks = list(client.get_all("/api/v1/banks/", {}))
    matches = _fuzzy_match_bank(all_banks, query)

    if len(matches) == 1:
        bank = matches[0]
        if interactive:
            console.print(
                f"[dim]Matched bank '{bank.get('name')}' "
                f"({bank.get('id')}).[/dim]"
            )
        else:
            logger.info(
                "Matched bank %s (%s)", bank.get("name"), bank.get("id")
            )
        return bank["id"]

    if not matches:
        show = all_banks
        msg = f"No banks match {query!r}."
    else:
        show = matches
        msg = f"Multiple banks match {query!r}; be more specific."

    _print_bank_table(show, console, interactive)
    raise click.ClickException(msg)


####################################################################
#
def _print_bank_table(
    banks: list[dict[str, Any]],
    console: Console,
    interactive: bool,
) -> None:
    """Print a table of banks for disambiguation."""
    if interactive:
        table = Table(title="Banks")
        table.add_column("Name", style="bold")
        table.add_column("Routing #")
        table.add_column("Currency")
        table.add_column("UUID", style="dim")
        for b in banks:
            table.add_row(
                b.get("name", ""),
                b.get("routing_number") or "",
                b.get("default_currency") or "",
                b.get("id", ""),
            )
        console.print(table)
    else:
        for b in banks:
            print(
                f"{b.get('id', '')}\t{b.get('name', '')}\t"
                f"{b.get('routing_number') or ''}\t"
                f"{b.get('default_currency') or ''}"
            )


####################################################################
#
def _fuzzy_match_account(
    accounts: list[dict[str, Any]], query: str
) -> list[dict[str, Any]]:
    """
    Return accounts whose name, account_number, or UUID id contain ``query``.

    Matching is case-insensitive on name, exact substring on the other
    fields.

    Args:
        accounts: List of bank account dicts from the API.
        query: The user-supplied search string.

    Returns:
        List of matching account dicts.
    """
    q = query.lower()
    matches: list[dict[str, Any]] = []
    for acct in accounts:
        if (
            q in (acct.get("name") or "").lower()
            or q in (acct.get("account_number") or "")
            or q in (acct.get("id") or "")
        ):
            matches.append(acct)
    return matches


####################################################################
#
def _resolve_account_by_query(
    client: MibudgeClient,
    query: str,
    *,
    console: Console,
    interactive: bool,
) -> str:
    """
    Fuzzy-match ``query`` against bank accounts and return the UUID.

    If exactly one account matches, return its ``id``. Otherwise print
    a table of matches (or all accounts if none matched) and raise a
    :class:`click.ClickException`.

    Args:
        client:      Authenticated MibudgeClient.
        query:       User-supplied search string.
        console:     Rich console for output.
        interactive: Whether to use rich formatting.

    Returns:
        The matched bank account's UUID.

    Raises:
        click.ClickException: On zero or multiple matches.
    """
    all_accounts = list(client.get_all("/api/v1/bank-accounts/", {}))
    matches = _fuzzy_match_account(all_accounts, query)

    if len(matches) == 1:
        acct = matches[0]
        if interactive:
            console.print(
                f"[dim]Matched account '{acct.get('name')}' "
                f"({acct.get('id')}).[/dim]"
            )
        else:
            logger.info(
                "Matched account %s (%s)",
                acct.get("name"),
                acct.get("id"),
            )
        return acct["id"]

    if not matches:
        show = all_accounts
        msg = f"No bank accounts match {query!r}."
    else:
        show = matches
        msg = f"Multiple bank accounts match {query!r}; be more specific."

    _print_account_table(show, console, interactive)
    raise click.ClickException(msg)


####################################################################
#
def _print_account_table(
    accounts: list[dict[str, Any]],
    console: Console,
    interactive: bool,
) -> None:
    """Print a table of bank accounts for disambiguation."""
    if interactive:
        table = Table(title="Bank Accounts")
        table.add_column("Name", style="bold")
        table.add_column("Type")
        table.add_column("Acct #")
        table.add_column("UUID", style="dim")
        for a in accounts:
            table.add_row(
                a.get("name", ""),
                a.get("account_type") or "",
                a.get("account_number") or "",
                a.get("id", ""),
            )
        console.print(table)
    else:
        for a in accounts:
            print(
                f"{a.get('id', '')}\t{a.get('name', '')}\t"
                f"{a.get('account_type') or ''}\t"
                f"{a.get('account_number') or ''}"
            )


########################################################################
########################################################################
#
def _dedup_key(
    tx_date: date | str,
    amount: Decimal | str,
    raw_description: str,
) -> tuple[str, str, str]:
    """
    Build a hashable 3-tuple dedup key from transaction fields.

    Used for **server-side dedup** (CSV vs already-imported
    transactions).  The key is (date, amount, raw_description).
    Count-based matching handles same-day, same-amount,
    same-merchant transactions correctly without needing the running
    balance (which diverges between BofA's CSV and the server's
    computed ``bank_account_posted_balance``).

    Args:
        tx_date: A date object or ISO datetime string from the API.
        amount: A Decimal or string representation of the amount.
        raw_description: The raw description string.

    Returns:
        A 3-tuple suitable as a dict/set key.
    """
    if isinstance(tx_date, str):
        # API returns ISO datetime like "2025-01-15T00:00:00Z".
        tx_date = datetime.fromisoformat(tx_date.replace("Z", "+00:00")).date()
    date_str = tx_date.isoformat()
    amount_str = str(Decimal(str(amount)).quantize(Decimal("0.01")))
    return (date_str, amount_str, raw_description)


####################################################################
#
def _intra_run_dedup_key(
    tx_date: date,
    amount: Decimal | str,
    raw_description: str,
    running_balance: Decimal,
) -> tuple[str, str, str, str]:
    """
    Build a hashable 4-tuple dedup key for intra-run dedup.

    Used when merging multiple CSV files within a single import run.
    The running balance is included because within a bank's CSV
    export it is consistent and distinguishes genuinely separate
    same-day, same-amount, same-merchant transactions (e.g. two
    $4.99 Apple charges each with a different running balance).

    Args:
        tx_date: Transaction date.
        amount: Transaction amount.
        raw_description: The raw description string.
        running_balance: BofA "Running Bal." column value.

    Returns:
        A 4-tuple suitable as a dict/set key.
    """
    date_str = tx_date.isoformat()
    amount_str = str(Decimal(str(amount)).quantize(Decimal("0.01")))
    bal_str = str(Decimal(str(running_balance)).quantize(Decimal("0.01")))
    return (date_str, amount_str, raw_description, bal_str)


####################################################################
#
def _fetch_existing(
    client: MibudgeClient,
    bank_account_id: str,
    start_date: date,
    end_date: date,
    user_timezone: str = "UTC",
) -> dict[tuple[str, str, str], list[tuple[str, str]]]:
    """
    Query the API for transactions in the date range and index them.

    Returns a mapping from the 3-tuple dedup key (date, amount,
    raw_description) to a **list** of ``(transaction_id,
    transaction_type)`` pairs.  Multiple entries under the same key
    represent genuinely distinct same-day, same-amount,
    same-description transactions (e.g. two coffee purchases).

    During import, the list is consumed (popped) so that each server
    transaction is matched to at most one CSV row.

    Filters on ``posted_date`` (not ``transaction_date``) so that
    transactions whose description-derived purchase date falls before
    the CSV window are still found and deduplicated correctly.

    Args:
        client: Authenticated MibudgeClient.
        bank_account_id: UUID of the bank account.
        start_date: Earliest posted date in the import file.
        end_date: Latest posted date in the import file.
        user_timezone: IANA timezone for the account owner.  Used to
            convert server UTC datetimes back to the local calendar
            date when building dedup keys.

    Returns:
        A mapping from 3-tuple dedup key to a list of
        ``(transaction_id, transaction_type)`` entries.
    """
    tz = ZoneInfo(user_timezone)
    existing: dict[tuple[str, str, str], list[tuple[str, str]]] = {}
    for tx in client.get_all(
        "/api/v1/transactions/",
        {
            "bank_account": bank_account_id,
            "posted_date_from": start_date.isoformat(),
            "posted_date_to": end_date.isoformat() + "T23:59:59",
        },
        page_size=_DEDUP_PAGE_SIZE,
    ):
        # Convert stored UTC datetime to the user's local calendar date
        # so the key matches the date-only value from the CSV.
        posted_utc = datetime.fromisoformat(
            tx["posted_date"].replace("Z", "+00:00")
        )
        local_date = posted_utc.astimezone(tz).date()
        key = _dedup_key(local_date, tx["amount"], tx["raw_description"])
        entry = (tx["id"], tx.get("transaction_type") or "")
        existing.setdefault(key, []).append(entry)
    return existing


####################################################################
#
def _post_transaction(
    client: MibudgeClient,
    bank_account_id: str,
    tx: ParsedTransaction,
    user_timezone: str,
) -> dict | None:
    """
    POST a single transaction to the API.

    Args:
        client: Authenticated MibudgeClient.
        bank_account_id: UUID of the bank account.
        tx: Parsed transaction from the CSV.
        user_timezone: IANA timezone name for the account owner (e.g.
            'America/Los_Angeles').  Used to anchor the date-only CSV
            value to midnight in the user's local timezone so the
            server stores the correct UTC value.

    Returns:
        The API response dict on success, or None on failure.
    """
    tz = ZoneInfo(user_timezone)
    posted_date = datetime(
        tx.transaction_date.year,
        tx.transaction_date.month,
        tx.transaction_date.day,
        tzinfo=tz,
    )
    payload = {
        "bank_account": bank_account_id,
        "amount": str(tx.amount),
        "posted_date": posted_date.isoformat(),
        "transaction_type": tx.transaction_type,
        "raw_description": tx.raw_description,
        "pending": tx.pending,
    }
    try:
        return client.post("/api/v1/transactions/", payload)
    except APIError as e:
        logger.error(
            "Failed to import transaction %s %s %s: %s",
            tx.transaction_date,
            tx.amount,
            tx.raw_description[:40],
            e,
        )
        return None


####################################################################
#
def _patch_transaction_type(
    client: MibudgeClient,
    transaction_id: str,
    transaction_type: str,
) -> bool:
    """
    PATCH an existing transaction's inferred type.

    Used to backfill ``transaction_type`` on rows that were imported
    before the parser had a matching pattern. The serializer allows
    PATCH of ``transaction_type`` after creation.

    Args:
        client: Authenticated MibudgeClient.
        transaction_id: UUID of the transaction to update.
        transaction_type: New TransactionType value.

    Returns:
        True on success, False on API error.
    """
    try:
        client.patch(
            f"/api/v1/transactions/{transaction_id}/",
            {"transaction_type": transaction_type},
        )
        return True
    except APIError as e:
        logger.error(
            "Failed to update transaction_type on %s to %r: %s",
            transaction_id,
            transaction_type,
            e,
        )
        return False


########################################################################
########################################################################
#
class ImportResult:
    """Accumulates import statistics and unrecognized descriptions."""

    def __init__(self) -> None:
        self.imported: int = 0
        self.skipped: int = 0
        self.updated: int = 0
        self.failed: int = 0
        self.unrecognized: list[str] = []


####################################################################
#
def import_statement(
    statement: ParsedStatement,
    bank_account_id: str,
    client: MibudgeClient,
    user_timezone: str,
    progress_callback: Callable[[int, int], None] | None = None,
    existing: (dict[tuple[str, str, str], list[tuple[str, str]]] | None) = None,
    *,
    dry_run: bool = False,
) -> ImportResult:
    """
    Import transactions from an already-parsed BofA statement.

    Parsing and validation happen at the CLI layer before this is
    called, so this function deals only with the API side: dedup,
    POST, and self-healing PATCH of ``transaction_type`` on rows whose
    server-side value is empty.

    Args:
        statement: A ``ParsedStatement`` from ``parse()``.
        bank_account_id: UUID of the target bank account.
        client: Authenticated MibudgeClient instance.
        user_timezone: IANA timezone name for the account owner.
            Passed to ``_post_transaction`` so date-only CSV values
            are anchored to midnight in the user's local timezone.
        progress_callback: Optional callback(current, total) invoked
            after processing each transaction.
        existing: Optional pre-fetched dedup map. When None, this
            function fetches the dedup window itself. The CLI layer
            pre-fetches so it can wrap the fetch in a rich status
            spinner (rich does not allow nested Live renderers, and
            the POST progress bar is already a Live renderer).
        dry_run: When True, classify each transaction (import / skip /
            update) but do not POST or PATCH anything.

    Returns:
        An ImportResult with counts and unrecognized descriptions.
    """
    result = ImportResult()
    transactions = statement.transactions

    if not transactions:
        logger.info("Statement contained no transactions.")
        return result

    logger.info("Importing %d transactions.", len(transactions))

    # Collect unrecognized transaction types for the summary.
    for tx in transactions:
        if tx.transaction_type == "":
            result.unrecognized.append(tx.raw_description)

    # Determine date range for the dedup query.
    start_date = min(tx.transaction_date for tx in transactions)
    end_date = max(tx.transaction_date for tx in transactions)

    # Fetch existing transactions in this window (unless the caller
    # pre-fetched so it could render a status spinner).
    if existing is None:
        existing = _fetch_existing(
            client, bank_account_id, start_date, end_date, user_timezone
        )
    logger.info(
        "Found %d existing transactions in date range %s to %s",
        len(existing),
        start_date,
        end_date,
    )

    total = len(transactions)
    for i, tx in enumerate(transactions):
        key = _dedup_key(
            tx.transaction_date,  # ParsedTransaction.transaction_date is the bank/posted date
            tx.amount,
            tx.raw_description,
        )
        matches = existing.get(key)
        if matches:
            # Pop one match so each server-side transaction is
            # consumed at most once.  This handles the "two coffees"
            # case: if the CSV has 2 entries and the server has 2,
            # both are skipped; if the server has 1, the second CSV
            # row is imported.
            tx_id, existing_type = matches.pop(0)
            # Backfill the transaction_type on duplicates when the
            # server has it empty but the parser has since learned to
            # classify this description. This lets "add a pattern and
            # re-run the import" work as the update path with no
            # separate backfill step.
            if existing_type == "" and tx.transaction_type != "":
                if dry_run:
                    result.updated += 1
                elif _patch_transaction_type(
                    client, tx_id, tx.transaction_type
                ):
                    result.updated += 1
                else:
                    result.failed += 1
            else:
                result.skipped += 1
        else:
            if dry_run:
                result.imported += 1
            else:
                resp = _post_transaction(
                    client, bank_account_id, tx, user_timezone
                )
                if resp is not None:
                    result.imported += 1
                else:
                    result.failed += 1

        if progress_callback:
            progress_callback(i + 1, total)

    return result


########################################################################
########################################################################
#
# File-extension -> (parse, validate_statement) dispatch table. We key
# on extension deliberately: OFX/QFX is a real spec and one parser
# handles any FI; CSVs are per-bank and their extension alone can't
# discriminate, so adding a second CSV parser will mean adding a
# ``--parser`` override flag rather than inventing an extension.
#
_PARSERS: dict[
    str,
    tuple[
        Callable[[Path], ParsedStatement],
        Callable[[ParsedStatement], list[str]],
    ],
] = {
    ".csv": (bofa_csv.parse, bofa_csv.validate_statement),
    ".ofx": (ofx.parse, ofx.validate_statement),
    ".qfx": (ofx.parse, ofx.validate_statement),
}


####################################################################
#
def _parse_and_validate(file_path: Path) -> ParsedStatement:
    """
    Parse a statement file and verify its internal consistency.

    Dispatches to a parser by file extension, then runs that parser's
    ``validate_statement()``. Any validation errors are treated as
    fatal -- we refuse to import from a file that does not internally
    balance because the symptoms after a partial import are much
    harder to untangle than a clean abort up front.

    Args:
        file_path: Path to a supported statement file (CSV or OFX/QFX).

    Returns:
        A validated ``ParsedStatement``.

    Raises:
        click.ClickException: On unsupported extension, parse failure,
            or validation failure.
    """
    suffix = file_path.suffix.lower()
    if suffix not in _PARSERS:
        raise click.ClickException(
            f"No parser for {file_path.name} (extension {suffix!r}). "
            f"Supported extensions: {sorted(_PARSERS)}."
        )
    parse_fn, validate_fn = _PARSERS[suffix]

    try:
        statement = parse_fn(file_path)
    except (ValueError, FileNotFoundError) as e:
        raise click.ClickException(f"Failed to parse {file_path}: {e}") from e

    errors = validate_fn(statement)
    if errors:
        msg = f"{file_path} failed internal validation:\n  - " + "\n  - ".join(
            errors
        )
        raise click.ClickException(msg)

    return statement


####################################################################
#
def _parse_all(
    file_paths: list[Path],
    console: Console,
    interactive: bool,
) -> list[ParsedStatement]:
    """
    Parse and validate every input file, sorted by statement start date.

    Enforces two cross-file invariants:

    1. All statements carrying an ``acct_id`` must report the *same*
       ``acct_id``. This prevents accidentally mixing, e.g., an
       ``apple-card/*.ofx`` glob with an ``apple-savings/*.ofx`` glob.
       Statements without an ``acct_id`` (BofA CSVs) are skipped by
       this check.
    2. Gaps between consecutive statements are flagged as warnings
       (not errors) -- the user may have legitimately not downloaded
       a month with zero activity, and re-running the import with the
       missing file added always dedups cleanly against what is
       already on the server.

    Args:
        file_paths: One or more paths to statement files.
        console:    Rich console for user-visible messages.
        interactive: Whether to render rich output.

    Returns:
        Validated ``ParsedStatement`` objects sorted by
        ``beginning_date``.

    Raises:
        click.ClickException: On parse/validation failure or mixed
            ``acct_id`` across files.
    """
    # Parse + validate each file with a rich progress bar. On
    # multi-file globs (e.g. 36 OFX statements) this phase can take
    # tens of seconds; without feedback it looks like a hang.
    statements: list[ParsedStatement] = []
    if interactive and len(file_paths) > 1:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task(
                "Parsing statements", total=len(file_paths)
            )
            for p in file_paths:
                progress.update(task, description=f"Parsing {p.name}")
                statements.append(_parse_and_validate(p))
                progress.advance(task)
    else:
        statements = [_parse_and_validate(p) for p in file_paths]
    statements.sort(key=lambda s: s.beginning_date)

    # Per-file summary (DEBUG). Re-run with --verbose to see this
    # table; it makes balance anomalies immediately diagnosable by
    # showing how each file claims its beginning/ending balance vs.
    # the transaction sum it carries.
    if logger.isEnabledFor(logging.DEBUG) and len(statements) > 1:
        logger.debug("Per-file statement summary (post-sort):")
        for s in statements:
            tx_sum = sum((t.amount for t in s.transactions), Decimal("0"))
            logger.debug(
                "  %s: %s -> %s | begin=%s end=%s sum_txs=%s (n=%d)",
                s.source_path,
                s.beginning_date,
                s.ending_date,
                s.beginning_balance,
                s.ending_balance,
                tx_sum,
                len(s.transactions),
            )

    # Cross-file ACCTID consistency (where applicable).
    ids = {s.acct_id for s in statements if s.acct_id}
    if len(ids) > 1:
        raise click.ClickException(
            "Files do not all belong to the same account. Mixed "
            f"ACCTID values found: {sorted(ids)}. Import one account's "
            "files at a time."
        )

    # Gap detection. Ignored when there's only one statement.
    for prev, curr in zip(statements, statements[1:]):
        # A gap is any span between one statement's end_date and the
        # next's beginning_date that's more than one day -- adjacent
        # statements can end and begin on the same day or one apart.
        delta = (curr.beginning_date - prev.ending_date).days
        if delta > 1:
            msg = (
                f"Gap of {delta} days between {prev.source_path} "
                f"(ends {prev.ending_date}) and {curr.source_path} "
                f"(starts {curr.beginning_date}). Any transactions in "
                f"that window will be missed unless you import the "
                f"covering file(s); re-runs with added files dedup "
                f"cleanly."
            )
            if interactive:
                console.print(f"[warning]Warning:[/warning] {msg}")
            else:
                logger.warning(msg)

    return statements


####################################################################
#
def _combine_statements(statements: list[ParsedStatement]) -> ParsedStatement:
    """
    Flatten a list of per-file ``ParsedStatement`` objects into one.

    The combined statement is what the API side of the importer sees:
    one date range, one set of transactions, one beginning/ending
    balance pair. The per-file objects remain available to the caller
    for diagnostics (gap warnings, mixed-account errors) that only
    make sense pre-combination.

    Args:
        statements: Parsed statements, already sorted by beginning_date.

    Returns:
        A synthetic ``ParsedStatement`` aggregating the inputs.
        ``ending_balance`` comes from the latest statement (older
        ending balances are stale once further activity is applied).
        ``acct_id`` and ``account_type`` come from the first
        statement that carries them; by the time we reach this
        function cross-file consistency has already been enforced.
    """
    assert statements, "caller must ensure at least one statement"
    first = statements[0]
    # Pick the ending anchor. For formats that tag the ending balance
    # with an "as of" timestamp (OFX LEDGERBAL <DTASOF>) prefer the
    # statement with the freshest DTASOF rather than the statement
    # with the latest ``beginning_date``: FIs like Apple populate
    # LEDGERBAL with the download-moment balance, so an older file
    # downloaded more recently is a better anchor than a file whose
    # window ends later but was downloaded weeks ago (its LEDGERBAL
    # misses any charges that were still authorizing at that time).
    # Fall back to last-by-beginning_date when no statement carries
    # ``ending_balance_as_of`` (BofA CSV, which binds ending balance
    # to a calendar date rather than an instant).
    dated = [s for s in statements if s.ending_balance_as_of is not None]
    if dated:
        last = max(
            dated,
            key=lambda s: (
                s.ending_balance_as_of or datetime.min.replace(tzinfo=UTC)
            ),
        )
        if last is not statements[-1]:
            logger.info(
                "Using %s as ending-balance anchor (LEDGERBAL as-of %s) "
                "rather than %s (as-of %s); freshest DTASOF wins to "
                "avoid stale pending-at-download-time drift.",
                last.source_path,
                last.ending_balance_as_of,
                statements[-1].source_path,
                statements[-1].ending_balance_as_of,
            )
    else:
        last = max(statements, key=lambda s: s.ending_date)

    # Intra-run dedup. Two common patterns produce duplicate
    # transactions across the combined file set:
    #   1. Monthly statements that overlap at the period boundary
    #      (the last day of month N reappears as the first day of
    #      month N+1).
    #   2. User-downloaded arbitrary date ranges that deliberately
    #      overlap -- downloading "Jan 1 -> Jun 30" and "Apr 1 ->
    #      today" is easier than being precise about seams, and
    #      the importer should tolerate that.
    # The intra-run key is (date, amount, raw_description,
    # running_balance). Including the running balance eliminates
    # false positives on same-day, same-amount, same-merchant
    # transactions (e.g. two $4.99 Apple charges): each has a
    # different running balance in the source file.  Two files
    # covering the same date range will carry the same running
    # balance for the same transaction, so true duplicates are
    # still caught.
    #
    # NOTE: this 4-tuple key is intentionally different from the
    # 3-tuple used for server-side dedup.  Within BofA's CSV
    # exports the running balance is consistent across downloads,
    # but the server's ``bank_account_posted_balance`` diverges
    # because it is computed at import time.
    transactions: list[ParsedTransaction] = []
    seen: set[tuple[str, str, str, str]] = set()
    duplicates = 0
    for s in statements:
        for tx in s.transactions:
            key = _intra_run_dedup_key(
                tx.transaction_date,
                tx.amount,
                tx.raw_description,
                tx.running_balance,
            )
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            transactions.append(tx)
    if duplicates:
        logger.info(
            "Dropped %d duplicate transaction(s) at statement boundaries.",
            duplicates,
        )

    # Sort the combined transaction list chronologically. Within a
    # single OFX file ``<STMTTRN>`` ordering is FI-dependent (Apple
    # writes newest-first), and across multiple files the per-statement
    # blocks yield runs that are each internally ordered but not
    # globally so. The per-transaction ``bank_account_posted_balance``
    # snapshot recorded by ``transaction_pre_save`` is only meaningful
    # when rows are POSTed in date order, so normalize here. Ties on
    # ``transaction_date`` keep their original relative order
    # (``sort`` is stable) which preserves intra-day sequencing from
    # the source file.
    transactions.sort(key=lambda tx: tx.transaction_date)

    acct_id = next((s.acct_id for s in statements if s.acct_id), None)
    account_type = next(
        (s.account_type for s in statements if s.account_type), None
    )

    # Summary totals must match the dedup'd transaction list, not the
    # raw sum across files -- otherwise validate_statement rejects
    # the combined statement on the summary-totals check.
    dedup_credits = sum(
        (tx.amount for tx in transactions if tx.amount > 0), Decimal("0")
    )
    dedup_debits = sum(
        (tx.amount for tx in transactions if tx.amount < 0), Decimal("0")
    )

    # Choose an authoritative combined beginning_balance. For sources
    # that report beginning_balance (BofA CSV summary block) the
    # earliest file's value is trustworthy; for sources where the
    # parser derives it from LEDGERBAL (OFX/QFX) the derived value
    # can be nonsense when the FI populates LEDGERBAL with the
    # download-time balance instead of the statement-end balance
    # (Apple's OFX exports do this). In that case derive the combined
    # beginning balance from the walk instead: if every transaction
    # in the combined run is applied to ``last.ending_balance`` in
    # reverse, the remainder must equal the true opening balance.
    sum_txs = sum((tx.amount for tx in transactions), Decimal("0"))
    if first.beginning_balance_reported:
        combined_beginning = first.beginning_balance
    else:
        combined_beginning = (last.ending_balance - sum_txs).quantize(
            Decimal("0.01")
        )
        logger.info(
            "Derived combined beginning balance %s from "
            "ending %s - sum(transactions) %s (per-file beginnings "
            "are not authoritative for this source format).",
            combined_beginning,
            last.ending_balance,
            sum_txs,
        )

    # Sanity check on the combined statement. If
    # ``combined_beginning + sum_txs != last.ending`` we would
    # silently post garbage to the server. With the OFX-derivation
    # above, this check effectively only fires for BofA-style
    # reported-beginning sources that have gaps or overlaps.
    expected_ending = combined_beginning + dedup_credits + dedup_debits
    expected_ending = expected_ending.quantize(Decimal("0.01"))
    actual_ending = last.ending_balance.quantize(Decimal("0.01"))
    if expected_ending != actual_ending and len(statements) > 1:
        logger.warning(
            "Combined statement does not balance: "
            "beginning (%s) + credits (%s) + debits (%s) = %s, "
            "but latest file reports ending balance %s "
            "(delta=%s). Re-run with --verbose for per-file details; "
            "files may have overlapping windows or a source that "
            "reports LEDGERBAL as the current balance rather than "
            "the statement-end balance.",
            first.beginning_balance,
            dedup_credits,
            dedup_debits,
            expected_ending,
            actual_ending,
            (expected_ending - actual_ending).quantize(Decimal("0.01")),
        )
        for s in statements:
            tx_sum = sum((t.amount for t in s.transactions), Decimal("0"))
            logger.warning(
                "  %s: %s -> %s | begin=%s end=%s sum_txs=%s (n=%d)",
                s.source_path,
                s.beginning_date,
                s.ending_date,
                s.beginning_balance,
                s.ending_balance,
                tx_sum,
                len(s.transactions),
            )

    return ParsedStatement(
        beginning_balance=combined_beginning,
        beginning_date=first.beginning_date,
        ending_balance=last.ending_balance,
        ending_date=last.ending_date,
        total_credits=dedup_credits,
        total_debits=dedup_debits,
        transactions=transactions,
        acct_id=acct_id,
        account_type=account_type,
        # Propagate the reported/derived flag from the earliest file;
        # consumers downstream may want to know (today, nothing does).
        beginning_balance_reported=first.beginning_balance_reported,
        source_path=(
            first.source_path
            if len(statements) == 1
            else f"{len(statements)} files ({first.source_path} .. {last.source_path})"
        ),
    )


####################################################################
#
def _create_bank_account(
    client: MibudgeClient,
    *,
    name: str,
    bank_id: str,
    account_type: str,
    account_number: str | None,
    beginning_balance: Decimal,
) -> dict:
    """
    POST a new BankAccount seeded with the CSV's beginning balance.

    Both ``posted_balance`` and ``available_balance`` are seeded to
    the CSV's beginning balance; BofA CSV exports contain only settled
    transactions so the two are equal at the statement start.

    Args:
        client: Authenticated MibudgeClient.
        name: Human-readable account name.
        bank_id: UUID of the parent Bank.
        account_type: Model choice code ("C"/"S"/"X").
        account_number: Optional account number (may be filled in later).
        beginning_balance: Seed balance from the statement summary.

    Returns:
        The created BankAccount dict from the API.
    """
    payload: dict[str, Any] = {
        "name": name,
        "bank": bank_id,
        "account_type": account_type,
        "posted_balance": str(beginning_balance),
        "available_balance": str(beginning_balance),
    }
    if account_number:
        payload["account_number"] = account_number
    return client.post("/api/v1/bank-accounts/", payload)


####################################################################
#
def _find_account_by_acctid(client: MibudgeClient, acct_id: str) -> dict | None:
    """
    Return the BankAccount dict whose ``account_number`` matches ``acct_id``.

    ``account_number`` is an ``EncryptedCharField`` server-side so we
    cannot filter on it via a query parameter -- encrypted values
    don't compare at the DB level. We fetch the user's accessible
    accounts instead and match client-side. The account list per user
    is always small.

    Args:
        client:  Authenticated MibudgeClient.
        acct_id: The OFX ACCTID to match against ``account_number``.

    Returns:
        The matching account dict, or ``None`` if no account has that
        ``account_number``.
    """
    for account in client.get_all("/api/v1/bank-accounts/", {}):
        if (account.get("account_number") or "") == acct_id:
            return account
    return None


####################################################################
#
def _resolve_bank_account(
    client: MibudgeClient,
    *,
    statement: ParsedStatement,
    account: str | None,
    create_account: bool,
    name: str | None,
    bank_id: str | None,
    account_type: str | None,
    account_number: str | None,
    console: Console,
    interactive: bool,
) -> str:
    """
    Return the target bank account UUID, creating the account if asked.

    Resolution order (first match wins):

    1. Explicit ``--account <query>`` -- fuzzy-matched against name,
       account number, and UUID. Required for formats like BofA CSV
       that don't carry an account identifier.
    2. Statement-carried ``acct_id`` (OFX) -> look up a BankAccount
       whose ``account_number`` equals that value. If found and the
       user did NOT pass ``--create-account``, use it. If found and
       the user DID pass ``--create-account``, refuse -- the command
       as given implies first-time import, but the account already
       exists.
    3. ``--create-account`` -- POST a new account seeded with the
       statement's beginning balance. ``account_type`` and
       ``account_number`` are derived from the statement when
       available (OFX); otherwise they come from the corresponding
       CLI flags.

    If none of the above apply, we can't guess what the user wants
    and an explicit error is the only safe answer.

    Args:
        client:         Authenticated MibudgeClient.
        statement:      The combined parsed statement (carries
            beginning_balance, acct_id, account_type).
        account:        Search string from --account (fuzzy-matched).
        create_account: Whether --create-account was passed.
        name, bank_id:  Required for --create-account.
        account_type:   CLI-supplied type; auto-filled from OFX when
            the statement has one.
        account_number: CLI-supplied number (CSV path only); for OFX
            the statement's acct_id is used.
        console:        Rich console for user-visible messages.
        interactive:    Whether to render rich output.

    Returns:
        The bank account UUID to import into.

    Raises:
        click.ClickException: On ambiguous or impossible input, or
            API failure.
    """
    # 1. Explicit --account: fuzzy-match against name/account_number/UUID.
    if account is not None:
        return _resolve_account_by_query(
            client, account, console=console, interactive=interactive
        )

    # 2. ACCTID lookup (OFX).
    matched: dict | None = None
    if statement.acct_id:
        matched = _find_account_by_acctid(client, statement.acct_id)

    if matched is not None:
        if create_account:
            raise click.ClickException(
                "--create-account was supplied, but an account already "
                f"exists for ACCTID {statement.acct_id!r} "
                f"(name={matched.get('name')!r}, id={matched.get('id')}). "
                "Drop --create-account to import into the existing "
                "account, or pass --account <query> to target a "
                "different one explicitly."
            )
        if interactive:
            console.print(
                f"[dim]Matched ACCTID {statement.acct_id} -> "
                f"existing account '{matched.get('name')}' "
                f"({matched.get('id')}).[/dim]"
            )
        else:
            logger.info(
                "Matched ACCTID %s -> existing account %s",
                statement.acct_id,
                matched.get("id"),
            )
        return matched["id"]

    # 3. --create-account path.
    if not create_account:
        if statement.acct_id:
            raise click.ClickException(
                f"No BankAccount found with account_number={statement.acct_id!r}. "
                "Re-run with --create-account (plus --name and --bank) to "
                "set it up, or --account <query> to target an existing "
                "account explicitly."
            )
        raise click.ClickException(
            "Either --account or --create-account must be supplied. "
            "(The source file does not carry an account identifier "
            "the importer can use to match an existing account.)"
        )

    assert name is not None and bank_id is not None
    # Resolve the bank query string to a UUID.
    resolved_bank_id = _resolve_bank_by_query(
        client, bank_id, console=console, interactive=interactive
    )
    # account_type and account_number: prefer the statement's values
    # (OFX) over the CLI flags, which on the OFX path are not even
    # accepted by the CLI validation.
    effective_type = statement.account_type or account_type
    if effective_type is None:
        raise click.ClickException(
            "--account-type is required when the source file does not "
            "identify the account type itself (this file does not)."
        )
    effective_number = statement.acct_id or account_number

    if interactive:
        console.print(
            f"[bold]Creating bank account[/bold] '{name}' "
            f"(beginning balance {statement.beginning_balance})..."
        )
    try:
        created = _create_bank_account(
            client,
            name=name,
            bank_id=resolved_bank_id,
            account_type=effective_type,
            account_number=effective_number,
            beginning_balance=statement.beginning_balance,
        )
    except APIError as e:
        raise click.ClickException(f"Failed to create bank account: {e}") from e

    account_id: str = created["id"]
    if interactive:
        console.print(f"[success]Created account {account_id}[/success]")
    else:
        logger.info("Created bank account %s", account_id)
    return account_id


####################################################################
#
def _verify_final_balance(
    client: MibudgeClient,
    bank_account_id: str,
    expected: Decimal,
) -> None:
    """
    Compare the account's posted balance against the statement's ending.

    This is the final cross-check: parser validation proved the CSV
    walks cleanly, and this proves the server's cumulative view after
    import matches. Mismatches are logged at ERROR but do NOT raise --
    the transactions are already imported and the surgery to fix a
    mismatch is case-by-case (duplicate prior import, missed pending
    transaction, etc.), not something this script should guess at.

    Args:
        client: Authenticated MibudgeClient.
        bank_account_id: UUID of the account just imported into.
        expected: ``statement.ending_balance`` from the parsed CSV.
    """
    try:
        account = client.get(f"/api/v1/bank-accounts/{bank_account_id}/")
    except APIError as e:
        logger.error(
            "Post-import balance check failed: could not fetch account %s: %s",
            bank_account_id,
            e,
        )
        return

    raw_posted = account.get("posted_balance")
    if raw_posted is None:
        logger.error(
            "Post-import balance check: account %s has no posted_balance.",
            bank_account_id,
        )
        return

    actual = Decimal(str(raw_posted)).quantize(Decimal("0.01"))
    expected_q = expected.quantize(Decimal("0.01"))
    if actual != expected_q:
        logger.error(
            "Post-import balance mismatch on account %s: server reports "
            "posted_balance=%s but statement ending balance was %s "
            "(delta=%s).",
            bank_account_id,
            actual,
            expected_q,
            actual - expected_q,
        )
    else:
        logger.info(
            "Post-import balance check OK: account %s posted_balance=%s "
            "matches statement ending balance.",
            bank_account_id,
            actual,
        )


########################################################################
########################################################################
#
def _resolve_local_ca_bundle() -> str:
    """
    Return the path to the mkcert root CA that signed the local dev cert.

    Only used when the caller explicitly opts in (via CLI flag or env var)
    because trusting arbitrary local CAs is not a safe default.

    Python's ssl module does not use the macOS Keychain, so we must pass
    the mkcert root CA explicitly rather than relying on system trust.

    Returns:
        Absolute path to the mkcert rootCA.pem.

    Raises:
        click.ClickException: If mkcert is not installed or its CA root
            cannot be found.
    """
    import subprocess

    try:
        result = subprocess.run(
            ["mkcert", "-CAROOT"],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise click.ClickException(
            "mkcert not found. Install it or pass --ca-bundle explicitly."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise click.ClickException(
            f"mkcert -CAROOT failed: {exc.stderr.strip()}"
        ) from exc
    path = Path(result.stdout.strip()) / "rootCA.pem"
    if not path.is_file():
        raise click.ClickException(
            f"mkcert root CA not found at {path}. Run `mkcert -install` first."
        )
    return str(path)


########################################################################
########################################################################
#
def _resolve_vault_secrets(vault_path: str) -> dict[str, str]:
    """
    Fetch credentials from HashiCorp Vault KV2.

    Uses standard Vault env vars (VAULT_ADDR, VAULT_TOKEN) for
    connection.  The secret at *vault_path* is expected to contain
    keys: ``url``, ``username``, ``password``.

    Args:
        vault_path: KV2 mount path, e.g. 'secret/data/mibudge/importer'
            or just 'mibudge/importer' (mount auto-detected).

    Returns:
        Dict with the secret's key-value data.

    Raises:
        click.ClickException: On connection or permission errors.
    """
    try:
        import hvac
    except ImportError as e:
        raise click.ClickException(
            "hvac package is required for Vault support: pip install hvac"
        ) from e

    client = hvac.Client()
    if not client.is_authenticated():
        raise click.ClickException(
            "Vault authentication failed. Check VAULT_ADDR and "
            "VAULT_TOKEN environment variables."
        )

    try:
        response = client.secrets.kv.v2.read_secret_version(
            path=vault_path,
            raise_on_deleted_version=True,
        )
    except hvac.exceptions.Forbidden as e:
        raise click.ClickException(
            f"Vault permission denied for path: {vault_path}"
        ) from e
    except hvac.exceptions.InvalidPath as e:
        raise click.ClickException(
            f"Vault secret not found at path: {vault_path}"
        ) from e

    return response["data"]["data"]


########################################################################
########################################################################
#
def _build_client(
    *,
    url: str | None,
    username: str | None,
    password: str | None,
    vault_path: str | None,
    ca_bundle: Path | None,
    trust_local_certs: bool,
    console: Console,
    interactive: bool,
) -> MibudgeClient:
    """
    Resolve credentials + TLS settings and return an unauthenticated client.

    Credential resolution order: CLI/env > Vault > error.
    The returned client must be entered as a context manager and have
    ``authenticate()`` called on it before use.

    Args:
        url, username, password: From CLI/env.
        vault_path: Optional KV2 path; if present, fills in missing
            credentials.
        ca_bundle: Explicit CA bundle path (overrides system CAs).
        trust_local_certs: If True, use the project-local mkcert bundle.
        console: Rich console for user-visible messages.
        interactive: Whether to render rich output.

    Returns:
        A configured (but not yet authenticated) ``MibudgeClient``.

    Raises:
        click.ClickException: If required credentials cannot be resolved.
    """
    vault_data: dict[str, str] = {}
    if vault_path:
        if interactive:
            console.print(
                f"[dim]Fetching credentials from Vault: {vault_path}[/dim]"
            )
        vault_data = _resolve_vault_secrets(vault_path)

    url = url or vault_data.get("url") or "https://localhost:8000"
    username = username or vault_data.get("username")
    password = password or vault_data.get("password")

    if not username:
        raise click.ClickException(
            "Username is required. Set --username, MIBUDGE_USERNAME, "
            "or provide it via Vault."
        )
    if not password:
        raise click.ClickException(
            "Password is required. Set --password, MIBUDGE_PASSWORD, "
            "or provide it via Vault."
        )

    verify: bool | str | None = None
    if ca_bundle is not None:
        verify = str(ca_bundle)
    elif trust_local_certs:
        verify = _resolve_local_ca_bundle()
        if interactive:
            console.print(f"[dim]Trusting local CA bundle: {verify}[/dim]")

    return MibudgeClient(url, username, password, verify=verify)


########################################################################
########################################################################
#
def _setup_logging(
    verbose: bool, interactive: bool, console: Console | None = None
) -> None:
    """
    Configure logging based on verbosity and output mode.

    When *interactive* is True, the ``RichHandler`` is bound to the
    supplied *console*. This must be the same Console instance passed
    to ``Progress(...)`` so rich's Live renderer coordinates redraws
    of the progress bar and log lines; otherwise each log write from
    a separate console clobbers the progress bar and produces jitter.
    """
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

    # httpx/httpcore emit an INFO-level line for every HTTP request.
    # That's one line per imported transaction, which both floods the
    # log and causes the rich progress bar to redraw on every request
    # (producing visible flicker). Raise them to WARNING unless the
    # user asked for DEBUG.
    if not verbose:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)


####################################################################
#
def _print_summary(
    console: Console,
    result: ImportResult,
    interactive: bool,
    *,
    dry_run: bool = False,
) -> None:
    """Print the import summary to the console."""
    if interactive:
        title = "Dry Run Summary" if dry_run else "Import Summary"
        verb = "Would import" if dry_run else "Imported"
        update_verb = "Would update" if dry_run else "Updated"
        table = Table(title=title, show_header=False)
        table.add_column("Metric", style="bold")
        table.add_column("Count", justify="right")
        table.add_row(verb, f"[success]{result.imported}[/success]")
        table.add_row("Skipped (duplicates)", f"[dim]{result.skipped}[/dim]")
        table.add_row(
            f"{update_verb} (type backfill)",
            f"[accent]{result.updated}[/accent]",
        )
        if result.failed:
            table.add_row("Failed", f"[error]{result.failed}[/error]")
        else:
            table.add_row("Failed", "0")
        console.print()
        console.print(table)

        if result.unrecognized:
            console.print()
            console.print(
                f"[warning]{len(result.unrecognized)} transaction(s) "
                f"with unrecognized type:[/warning]"
            )
            seen: set[str] = set()
            for desc in result.unrecognized:
                if desc not in seen:
                    seen.add(desc)
                    console.print(f"  [dim]{desc}[/dim]")
    else:
        prefix = "DRY RUN. " if dry_run else "Done. "
        verb = "Would import" if dry_run else "Imported"
        update_verb = "Would update" if dry_run else "Updated"
        print(
            f"{prefix}{verb}: {result.imported}, "
            f"Skipped (duplicates): {result.skipped}, "
            f"{update_verb}: {result.updated}, "
            f"Failed: {result.failed}."
        )
        if result.unrecognized:
            seen = set()
            for desc in result.unrecognized:
                if desc not in seen:
                    seen.add(desc)
                    print(f"  Unrecognized type: {desc}")


########################################################################
########################################################################
#
@click.command(
    context_settings={"auto_envvar_prefix": "MIBUDGE"},
    help=(
        "Import one or more bank statement files (CSV or OFX/QFX) into "
        "mibudge via its REST API. Files can be passed via -f "
        "(repeatable) or as positional arguments, so shell globs like "
        "*.ofx work."
    ),
)
@click.option(
    "--url",
    "-u",
    default=None,
    help="Base URL of the mibudge API.  [default: https://localhost:8000]",
)
@click.option("--username", default=None, help="API username.")
@click.option(
    "--password",
    default=None,
    help="API password (prefer env var or Vault over CLI flag).",
)
@click.option(
    "--vault-path",
    default=None,
    help="Vault KV2 path for credentials (e.g. 'mibudge/importer').",
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
    "--dry-run",
    "-n",
    is_flag=True,
    help=(
        "Show what would be imported without making any changes. "
        "Parses files, authenticates, and checks for duplicates, "
        "but does not POST or PATCH any transactions."
    ),
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Enable verbose (DEBUG) logging.",
)
@click.option(
    "--plain",
    is_flag=True,
    help="Disable rich output (auto-disabled when not a TTY).",
)
@theme_option
@click.option(
    "--file",
    "-f",
    "flag_files",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    multiple=True,
    help=(
        "Path to a statement file. Repeatable. Positional arguments "
        "are also accepted, so shell globs (e.g. '*.ofx') work too."
    ),
)
@click.argument(
    "positional_files",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    nargs=-1,
)
@click.option(
    "--account",
    "-a",
    default=None,
    help=(
        "Bank account — a UUID, name, or account number. If the "
        "string matches exactly one account it is used; otherwise "
        "all matches (or all accounts) are shown. Overrides any "
        "ACCTID auto-match. Omit with --create-account, or when "
        "importing OFX whose ACCTID already matches."
    ),
)
@click.option(
    "--create-account",
    is_flag=True,
    help=(
        "Create the target bank account before importing. For OFX the "
        "account type and account number are taken from the file; for "
        "CSV they must be supplied via --account-type and optionally "
        "--account-number. Always requires --name and --bank. Refused "
        "if an account already matches the OFX ACCTID."
    ),
)
@click.option(
    "--name",
    default=None,
    help="Name for the new bank account (with --create-account).",
)
@click.option(
    "--bank",
    default=None,
    help=(
        "Parent bank — a UUID, name, or routing number. If the "
        "string matches exactly one bank it is used; otherwise "
        "all matches (or all banks) are shown for disambiguation."
    ),
)
@click.option(
    "--account-type",
    type=click.Choice(list(_ACCOUNT_TYPE_CHOICES.keys())),
    default=None,
    help=(
        "Account type for --create-account. Required for CSV imports; "
        "ignored for OFX (the statement carries the type)."
    ),
)
@click.option(
    "--account-number",
    default=None,
    help=(
        "Account number for --create-account (CSV path). Ignored for "
        "OFX -- the statement's ACCTID is used."
    ),
)
def cli_cmd(
    url: str | None,
    username: str | None,
    password: str | None,
    vault_path: str | None,
    ca_bundle: Path | None,
    trust_local_certs: bool,
    dry_run: bool,
    verbose: bool,
    plain: bool,
    theme_name: str,
    flag_files: tuple[Path, ...],
    positional_files: tuple[Path, ...],
    account: str | None,
    create_account: bool,
    name: str | None,
    bank: str | None,
    account_type: str | None,
    account_number: str | None,
) -> None:
    """CLI entry point for the statement importer."""
    console = Console(theme=get_theme(theme_name).rich, stderr=True)
    interactive = console.is_terminal and not plain
    _setup_logging(verbose, interactive, console=console)

    # --- Collect and validate inputs ---
    file_paths: list[Path] = list(flag_files) + list(positional_files)
    if not file_paths:
        raise click.UsageError(
            "At least one statement file is required. Pass paths "
            "positionally (e.g. '*.ofx') or with -f."
        )

    if dry_run and create_account:
        raise click.UsageError(
            "--dry-run and --create-account are mutually exclusive."
        )
    if create_account and account:
        raise click.UsageError(
            "--create-account and --account are mutually exclusive."
        )
    if create_account:
        missing = [
            flag
            for flag, val in [("--name", name), ("--bank", bank)]
            if not val
        ]
        if missing:
            raise click.UsageError(
                f"--create-account requires: {', '.join(missing)}."
            )
    else:
        # Not creating: reject create-only flags so the user notices
        # rather than silently having them ignored.
        stray = [
            flag
            for flag, val in [
                ("--name", name),
                ("--bank", bank),
                ("--account-type", account_type),
                ("--account-number", account_number),
            ]
            if val
        ]
        if stray:
            raise click.UsageError(
                f"{', '.join(stray)} only apply with --create-account."
            )

    # --- Parse + validate every file up front (abort before any API calls) ---
    per_file_statements = _parse_all(file_paths, console, interactive)
    statement = _combine_statements(per_file_statements)
    if interactive:
        console.print(
            f"[dim]Parsed {len(statement.transactions)} transaction(s) "
            f"from {len(per_file_statements)} file(s) "
            f"({statement.beginning_date} -> {statement.ending_date}).[/dim]"
        )
    if dry_run and interactive:
        console.print(
            "[bold warning]DRY RUN[/bold warning] — no changes will be made."
        )

    bank_id_str: str | None = bank
    account_type_code: str | None = (
        _ACCOUNT_TYPE_CHOICES[account_type] if account_type else None
    )

    # --- Run the import ---
    try:
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
                with console.status("[bold]Authenticating..."):
                    client.authenticate()
                console.print("[success]Authenticated.[/success]")
            else:
                client.authenticate()
                logger.info("Authenticated.")

            user_timezone: str = client.get("/api/v1/users/me/").get(
                "timezone", "UTC"
            )
            logger.info("User timezone: %s", user_timezone)

            account_id = _resolve_bank_account(
                client,
                statement=statement,
                account=account,
                create_account=create_account,
                name=name,
                bank_id=bank_id_str,
                account_type=account_type_code,
                account_number=account_number,
                console=console,
                interactive=interactive,
            )

            # Pre-fetch the dedup window up here so we can wrap it in
            # a status spinner; rich does not allow a status Live
            # inside the Progress Live we start below.
            txs = statement.transactions
            dedup_start = (
                min(tx.transaction_date for tx in txs) if txs else None
            )
            dedup_end = max(tx.transaction_date for tx in txs) if txs else None
            existing: dict[tuple[str, str, str], list[tuple[str, str]]] = {}
            if txs and dedup_start is not None and dedup_end is not None:
                if interactive:
                    with console.status(
                        f"[bold]Fetching existing transactions "
                        f"({dedup_start} -> {dedup_end})..."
                    ):
                        existing = _fetch_existing(
                            client,
                            account_id,
                            dedup_start,
                            dedup_end,
                            user_timezone,
                        )
                else:
                    existing = _fetch_existing(
                        client,
                        account_id,
                        dedup_start,
                        dedup_end,
                        user_timezone,
                    )

            if interactive:
                progress = Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    MofNCompleteColumn(),
                    TextColumn(
                        "[success]+{task.fields[imported]}[/success] "
                        "[dim]~{task.fields[skipped]}[/dim] "
                        "[error]-{task.fields[failed]}[/error]"
                    ),
                    TimeElapsedColumn(),
                    console=console,
                )
                task_id = progress.add_task(
                    "Importing",
                    total=len(statement.transactions),
                    imported=0,
                    skipped=0,
                    failed=0,
                )

                def _progress_cb(current: int, total: int) -> None:
                    progress.update(task_id, completed=current)

                with progress:
                    result = import_statement(
                        statement,
                        account_id,
                        client,
                        user_timezone,
                        _progress_cb,
                        existing=existing,
                        dry_run=dry_run,
                    )
                    progress.update(
                        task_id,
                        imported=result.imported,
                        skipped=result.skipped,
                        failed=result.failed,
                    )
            else:
                result = import_statement(
                    statement,
                    account_id,
                    client,
                    user_timezone,
                    existing=existing,
                    dry_run=dry_run,
                )

            if not dry_run:
                # Post-import cross-check -- error-level, non-fatal.
                _verify_final_balance(
                    client, account_id, statement.ending_balance
                )

    except AuthenticationError as e:
        raise click.ClickException(str(e)) from e
    except KeyboardInterrupt as e:
        raise click.Abort() from e

    _print_summary(console, result, interactive, dry_run=dry_run)

    if result.failed > 0:
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
