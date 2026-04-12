"""
Import transactions from a BofA CSV export into mibudge.

This is a click.group with two subcommands:

* ``import`` -- parse a BofA CSV export and POST its transactions to the
  mibudge REST API, optionally creating the target bank account on the
  fly from the CSV's own summary block.
* ``banks`` -- list the banks visible to the authenticated user along
  with their UUIDs (the values accepted by ``--bank``).

Typical usage::

    # Import into an existing account:
    uv run python -m importers import \\
        --file ~/Downloads/stmt.csv \\
        --account <bank-account-uuid>

    # First-time import: create the account and seed its beginning
    # balance from the CSV summary:
    uv run python -m importers banks
    uv run python -m importers import \\
        --file ~/Downloads/stmt.csv \\
        --create-account \\
        --name "Personal Checking" \\
        --bank <bank-uuid> \\
        --account-type checking

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
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

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
from importers.parsers.bofa_csv import (
    ParsedStatement,
    ParsedTransaction,
    parse,
    validate_statement,
)

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
def _dedup_key(
    tx_date: date | str,
    amount: Decimal | str,
    raw_description: str,
) -> tuple[str, str, str]:
    """
    Build a hashable dedup key from transaction fields.

    Normalizes date to YYYY-MM-DD and amount to a two-decimal string so
    that values from the parser and from the API response can be compared
    directly.

    Args:
        tx_date: A date object or ISO datetime string from the API.
        amount: A Decimal or string representation of the amount.
        raw_description: The raw description string.

    Returns:
        A (date_str, amount_str, description) tuple.
    """
    if isinstance(tx_date, str):
        # API returns ISO datetime like "2025-01-15T00:00:00Z".
        tx_date = datetime.fromisoformat(tx_date.replace("Z", "+00:00")).date()
    date_str = tx_date.isoformat()
    amount_str = str(Decimal(str(amount)).quantize(Decimal("0.01")))
    return (date_str, amount_str, raw_description)


####################################################################
#
def _fetch_existing(
    client: MibudgeClient,
    bank_account_id: str,
    start_date: date,
    end_date: date,
) -> dict[tuple[str, str, str], tuple[str, str]]:
    """
    Query the API for transactions in the date range and index them.

    Args:
        client: Authenticated MibudgeClient.
        bank_account_id: UUID of the bank account.
        start_date: Earliest date in the import file.
        end_date: Latest date in the import file.

    Returns:
        A mapping from dedup key -> (transaction_id, transaction_type)
        so the caller can both dedup and, where appropriate, PATCH an
        existing transaction whose type is empty.
    """
    existing: dict[tuple[str, str, str], tuple[str, str]] = {}
    for tx in client.get_all(
        "/api/v1/transactions/",
        {
            "bank_account": bank_account_id,
            "date_from": start_date.isoformat(),
            "date_to": end_date.isoformat() + "T23:59:59",
        },
        page_size=_DEDUP_PAGE_SIZE,
    ):
        key = _dedup_key(
            tx["transaction_date"],
            tx["amount"],
            tx["raw_description"],
        )
        existing[key] = (tx["id"], tx.get("transaction_type") or "")
    return existing


####################################################################
#
def _post_transaction(
    client: MibudgeClient,
    bank_account_id: str,
    tx: ParsedTransaction,
) -> dict | None:
    """
    POST a single transaction to the API.

    Args:
        client: Authenticated MibudgeClient.
        bank_account_id: UUID of the bank account.
        tx: Parsed transaction from the CSV.

    Returns:
        The API response dict on success, or None on failure.
    """
    payload = {
        "bank_account": bank_account_id,
        "amount": str(tx.amount),
        "transaction_date": datetime.combine(
            tx.transaction_date, datetime.min.time()
        ).isoformat(),
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
    progress_callback: Callable[[int, int], None] | None = None,
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
        progress_callback: Optional callback(current, total) invoked
            after processing each transaction.

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

    # Fetch existing transactions in this window.
    existing = _fetch_existing(client, bank_account_id, start_date, end_date)
    logger.info(
        "Found %d existing transactions in date range %s to %s",
        len(existing),
        start_date,
        end_date,
    )

    total = len(transactions)
    for i, tx in enumerate(transactions):
        key = _dedup_key(tx.transaction_date, tx.amount, tx.raw_description)
        match = existing.get(key)
        if match is not None:
            tx_id, existing_type = match
            # Backfill the transaction_type on duplicates when the
            # server has it empty but the parser has since learned to
            # classify this description. This lets "add a pattern and
            # re-run the import" work as the update path with no
            # separate backfill step.
            if existing_type == "" and tx.transaction_type != "":
                if _patch_transaction_type(client, tx_id, tx.transaction_type):
                    result.updated += 1
                    existing[key] = (tx_id, tx.transaction_type)
                else:
                    result.failed += 1
            else:
                result.skipped += 1
        else:
            resp = _post_transaction(client, bank_account_id, tx)
            if resp is not None:
                result.imported += 1
                # Intentionally NOT adding this key to `existing`. Our
                # dedup key (date, amount, raw_description) is too
                # coarse to tell a genuine repeat transaction (two
                # same-amount coffees at the same merchant on the same
                # day, duplicate small recurring charges, etc.) from a
                # byte-identical CSV row. Treating in-file repeats as
                # duplicates silently drops real transactions, which
                # is worse than the unlikely case of a malformed CSV
                # producing two identical rows. Re-runs of the import
                # still dedup correctly against the server snapshot
                # taken at the start of this call.
            else:
                result.failed += 1

        if progress_callback:
            progress_callback(i + 1, total)

    return result


########################################################################
########################################################################
#
def _parse_and_validate(file_path: Path) -> ParsedStatement:
    """
    Parse the BofA CSV and verify internal consistency.

    Runs ``parse()`` and then ``validate_statement()``. Any validation
    errors are treated as fatal -- we refuse to import from a CSV that
    does not internally balance because the symptoms after a partial
    import are much harder to untangle than a clean abort up front.

    Args:
        file_path: Path to the BofA CSV export.

    Returns:
        A validated ``ParsedStatement``.

    Raises:
        click.ClickException: On parse or validation failure.
    """
    try:
        statement = parse(file_path)
    except (ValueError, FileNotFoundError) as e:
        raise click.ClickException(f"Failed to parse {file_path}: {e}") from e

    errors = validate_statement(statement)
    if errors:
        msg = (
            f"CSV {file_path} failed internal validation:\n  - "
            + "\n  - ".join(errors)
        )
        raise click.ClickException(msg)

    return statement


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

    When ``create_account`` is True, POSTs a new account seeded with
    the statement's beginning balance. Otherwise returns the supplied
    ``account`` UUID unchanged.

    Args:
        client: Authenticated MibudgeClient.
        statement: The parsed statement (provides ``beginning_balance``
            when creating).
        account: UUID of an existing account, if not creating.
        create_account: True to create a new account.
        name, bank_id, account_type, account_number: Required/optional
            create-time fields (validated by the caller).
        console: Rich console for user-visible messages.
        interactive: Whether to render rich output.

    Returns:
        The bank account UUID to import into.

    Raises:
        click.ClickException: On API failure.
    """
    if not create_account:
        assert account is not None  # guaranteed by CLI validation
        return account

    assert name is not None and bank_id is not None and account_type is not None
    if interactive:
        console.print(
            f"[bold]Creating bank account[/bold] '{name}' "
            f"(beginning balance {statement.beginning_balance})..."
        )
    try:
        created = _create_bank_account(
            client,
            name=name,
            bank_id=bank_id,
            account_type=account_type,
            account_number=account_number,
            beginning_balance=statement.beginning_balance,
        )
    except APIError as e:
        raise click.ClickException(f"Failed to create bank account: {e}") from e

    account_id: str = created["id"]
    if interactive:
        console.print(f"[green]Created account {account_id}[/green]")
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
# Project-relative path to the mkcert-issued server cert used by the
# local dev stack. Opt-in via --trust-local-certs / MIBUDGE_TRUST_LOCAL_CERTS
# because trusting arbitrary local files is not a safe default.
_LOCAL_CA_BUNDLE = Path("deployment") / "ssl" / "ssl_crt.pem"


def _resolve_local_ca_bundle() -> str:
    """
    Return the path to the project-local dev CA bundle.

    Only used when the caller explicitly opts in (via CLI flag or
    env var) because we do not want to silently trust files based on
    the current working directory.

    Returns:
        Absolute path to ``deployment/ssl/ssl_crt.pem``.

    Raises:
        click.ClickException: If the expected file does not exist
            (e.g. the importer is being run outside the project root).
    """
    path = Path.cwd() / _LOCAL_CA_BUNDLE
    if not path.is_file():
        raise click.ClickException(
            f"Local CA bundle not found at {path}. Run the importer "
            f"from the project root, or pass --ca-bundle explicitly."
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
) -> None:
    """Print the import summary to the console."""
    if interactive:
        table = Table(title="Import Summary", show_header=False)
        table.add_column("Metric", style="bold")
        table.add_column("Count", justify="right")
        table.add_row("Imported", f"[green]{result.imported}[/green]")
        table.add_row("Skipped (duplicates)", f"[dim]{result.skipped}[/dim]")
        table.add_row(
            "Updated (type backfill)", f"[cyan]{result.updated}[/cyan]"
        )
        if result.failed:
            table.add_row("Failed", f"[red]{result.failed}[/red]")
        else:
            table.add_row("Failed", "0")
        console.print()
        console.print(table)

        if result.unrecognized:
            console.print()
            console.print(
                f"[yellow]{len(result.unrecognized)} transaction(s) "
                f"with unrecognized type:[/yellow]"
            )
            seen: set[str] = set()
            for desc in result.unrecognized:
                if desc not in seen:
                    seen.add(desc)
                    console.print(f"  [dim]{desc}[/dim]")
    else:
        print(
            f"Done. Imported: {result.imported}, "
            f"Skipped (duplicates): {result.skipped}, "
            f"Updated: {result.updated}, "
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
# Common options shared between the ``import`` and ``banks`` subcommands.
# Click doesn't have first-class option groups, so we hang them off the
# parent ``cli`` group and stash the resolved config in ``ctx.obj``.
#
@click.group(
    context_settings={"auto_envvar_prefix": "MIBUDGE"},
    help="Mibudge bank statement importer.",
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
        "Trust the project-local mkcert cert at "
        "deployment/ssl/ssl_crt.pem (relative to the current directory)."
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
@click.pass_context
def cli_group(
    ctx: click.Context,
    url: str | None,
    username: str | None,
    password: str | None,
    vault_path: str | None,
    ca_bundle: Path | None,
    trust_local_certs: bool,
    verbose: bool,
    plain: bool,
) -> None:
    """Parent group: resolves shared connection/TLS/logging options."""
    console = Console(stderr=True)
    interactive = console.is_terminal and not plain
    _setup_logging(verbose, interactive, console=console)

    ctx.ensure_object(dict)
    ctx.obj.update(
        {
            "url": url,
            "username": username,
            "password": password,
            "vault_path": vault_path,
            "ca_bundle": ca_bundle,
            "trust_local_certs": trust_local_certs,
            "verbose": verbose,
            "console": console,
            "interactive": interactive,
        }
    )


########################################################################
########################################################################
#
@cli_group.command("import", help="Import a BofA CSV export into mibudge.")
@click.option(
    "--file",
    "-f",
    "file_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="Path to the BofA CSV export file.",
)
@click.option(
    "--account",
    "-a",
    default=None,
    help="Bank account UUID to import into (omit with --create-account).",
)
@click.option(
    "--create-account",
    is_flag=True,
    help=(
        "Create the target bank account from the CSV summary before "
        "importing. Requires --name, --bank, and --account-type. "
        "Mutually exclusive with --account."
    ),
)
@click.option(
    "--name",
    default=None,
    help="Name for the new bank account (with --create-account).",
)
@click.option(
    "--bank",
    type=click.UUID,
    default=None,
    help=(
        "UUID of the parent Bank (with --create-account). "
        "Use the 'banks' subcommand to list available banks."
    ),
)
@click.option(
    "--account-type",
    type=click.Choice(list(_ACCOUNT_TYPE_CHOICES.keys())),
    default=None,
    help="Account type (with --create-account).",
)
@click.option(
    "--account-number",
    default=None,
    help="Optional account number (with --create-account).",
)
@click.pass_context
def import_cmd(
    ctx: click.Context,
    file_path: Path,
    account: str | None,
    create_account: bool,
    name: str | None,
    bank: Any,  # click.UUID yields uuid.UUID
    account_type: str | None,
    account_number: str | None,
) -> None:
    """CLI entry point for the BofA CSV importer."""
    console: Console = ctx.obj["console"]
    interactive: bool = ctx.obj["interactive"]

    # --- Validate flag combinations ---
    if create_account and account:
        raise click.UsageError(
            "--create-account and --account are mutually exclusive."
        )
    if not create_account and not account:
        raise click.UsageError(
            "Either --account or --create-account must be supplied."
        )
    if create_account:
        missing = [
            flag
            for flag, val in [
                ("--name", name),
                ("--bank", bank),
                ("--account-type", account_type),
            ]
            if not val
        ]
        if missing:
            raise click.UsageError(
                f"--create-account requires: {', '.join(missing)}."
            )
    else:
        # --account mode: reject create-only flags so the user doesn't
        # think they've supplied data that will be respected.
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

    # --- Parse + validate up front (abort before any API calls) ---
    statement = _parse_and_validate(file_path)
    if interactive:
        console.print(
            f"[dim]Parsed {len(statement.transactions)} transaction(s) "
            f"from {file_path} "
            f"({statement.beginning_date} -> {statement.ending_date}).[/dim]"
        )

    bank_id_str: str | None = str(bank) if bank is not None else None
    account_type_code: str | None = (
        _ACCOUNT_TYPE_CHOICES[account_type] if account_type else None
    )

    # --- Run the import ---
    try:
        with _build_client(
            url=ctx.obj["url"],
            username=ctx.obj["username"],
            password=ctx.obj["password"],
            vault_path=ctx.obj["vault_path"],
            ca_bundle=ctx.obj["ca_bundle"],
            trust_local_certs=ctx.obj["trust_local_certs"],
            console=console,
            interactive=interactive,
        ) as client:
            if interactive:
                with console.status("[bold]Authenticating..."):
                    client.authenticate()
                console.print("[green]Authenticated.[/green]")
            else:
                client.authenticate()
                logger.info("Authenticated.")

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

            if interactive:
                progress = Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    MofNCompleteColumn(),
                    TextColumn(
                        "[green]+{task.fields[imported]}[/green] "
                        "[dim]~{task.fields[skipped]}[/dim] "
                        "[red]-{task.fields[failed]}[/red]"
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
                        statement, account_id, client, _progress_cb
                    )
                    progress.update(
                        task_id,
                        imported=result.imported,
                        skipped=result.skipped,
                        failed=result.failed,
                    )
            else:
                result = import_statement(statement, account_id, client)

            # Post-import cross-check -- error-level, non-fatal.
            _verify_final_balance(client, account_id, statement.ending_balance)

    except AuthenticationError as e:
        raise click.ClickException(str(e)) from e
    except KeyboardInterrupt as e:
        raise click.Abort() from e

    _print_summary(console, result, interactive)

    if result.failed > 0:
        raise SystemExit(1)


########################################################################
########################################################################
#
@cli_group.command(
    "banks", help="List banks visible to the authenticated user."
)
@click.pass_context
def banks_cmd(ctx: click.Context) -> None:
    """Print a table of banks with their UUIDs, for use with --bank."""
    console: Console = ctx.obj["console"]
    interactive: bool = ctx.obj["interactive"]

    try:
        with _build_client(
            url=ctx.obj["url"],
            username=ctx.obj["username"],
            password=ctx.obj["password"],
            vault_path=ctx.obj["vault_path"],
            ca_bundle=ctx.obj["ca_bundle"],
            trust_local_certs=ctx.obj["trust_local_certs"],
            console=console,
            interactive=interactive,
        ) as client:
            if interactive:
                with console.status("[bold]Authenticating..."):
                    client.authenticate()
            else:
                client.authenticate()

            banks = list(client.get_all("/api/v1/banks/", {}))
    except AuthenticationError as e:
        raise click.ClickException(str(e)) from e

    if not banks:
        if interactive:
            console.print("[yellow]No banks found.[/yellow]")
        else:
            print("No banks found.")
        return

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


########################################################################
########################################################################
#
def cli() -> None:
    """Load .env and invoke the click group."""
    load_dotenv()
    cli_group()


if __name__ == "__main__":
    cli()
