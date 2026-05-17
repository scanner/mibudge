"""
Replay saved BofA scrape files into mibudge without logging in to BofA.

Loads one or more JSON files written by ``import_bofa_live --save-dir`` and
runs them through the same dedup + POST pipeline as the live scraper, but
without requiring a browser or BofA credentials.

Useful for:
- Re-importing after fixing an issue without re-scraping
- Comparing coverage against CSV exports before committing an import
- Dry-running an import to preview what would be created

Usage::

    uv run python -m importers.import_bofa_saved \
        saved/2026-05-15-103045-1234.json \
        saved/2026-05-15-103045-5678.json \
        [--dry-run] [--run-funding] [--verbose]
"""

# system imports
#
import logging
from pathlib import Path

# 3rd party imports
#
import click
from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

# Project imports
#
from importers.client import AuthenticationError
from importers.import_bofa_live import (
    SavedScrape,
    SavedTransaction,
    _build_statement,
    _extract_last_four,
    _resolve_pending_transactions,
    _resolve_truncated_descriptions,
    load_saved_scrape,
)
from importers.import_transactions import (
    _build_client,
    _fetch_existing,
    _mark_imported,
    _resolve_account_by_query,
    _run_funding,
    import_statement,
)
from importers.theme import get_theme, theme_option

logger = logging.getLogger(__name__)


########################################################################
########################################################################
#
class _ReplayAccount:
    """Mock bofa_scraper Account backed by a ``SavedScrape``.

    Implements the same interface as bofa_scraper's Account object so that
    ``_build_statement`` can be called without a real browser session.
    """

    def __init__(self, saved: SavedScrape) -> None:
        self._saved = saved

    def get_name(self) -> str:
        return self._saved.account_name

    def get_balance(self) -> float:
        return float(self._saved.ending_balance)

    def get_transactions(self) -> list[SavedTransaction]:
        return self._saved.transactions


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


########################################################################
########################################################################
#
@click.command(
    context_settings={"auto_envvar_prefix": "MIBUDGE"},
    help=(
        "Replay saved BofA scrape files into mibudge without logging in "
        "to Bank of America.\n\n"
        "Accepts one or more JSON files written by "
        "``import_bofa_live --save-dir`` and runs them through the same "
        "dedup + POST pipeline as the live scraper.  mibudge credentials "
        "follow the same resolution order as the other importers.\n\n"
        "Useful for re-importing after a fix, dry-running to preview what "
        "would be created, or verifying coverage against CSV exports."
    ),
)
@click.argument(
    "files",
    nargs=-1,
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
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
    help="Trust the mkcert root CA.  Required for local dev with mkcert TLS.",
)
@click.option(
    "--dry-run",
    "-n",
    is_flag=True,
    help=(
        "Show what would be imported without making any changes. "
        "Checks for duplicates but does not POST or PATCH."
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
@click.option("--verbose", "-v", is_flag=True, help="Enable DEBUG logging.")
@click.option(
    "--plain",
    is_flag=True,
    help="Disable rich output (auto-disabled when not a TTY).",
)
@theme_option
def cli_cmd(
    files: tuple[Path, ...],
    url: str | None,
    username: str | None,
    password: str | None,
    vault_path: str | None,
    ca_bundle: Path | None,
    trust_local_certs: bool,
    dry_run: bool,
    run_funding: bool,
    verbose: bool,
    plain: bool,
    theme_name: str,
) -> None:
    """CLI entry point for replaying saved BofA scrape files."""
    console = Console(theme=get_theme(theme_name).rich, stderr=True)
    interactive = console.is_terminal and not plain
    _setup_logging(verbose, interactive, console=console)

    if dry_run and interactive:
        console.print(
            "[bold warning]DRY RUN[/bold warning] — no changes will be made."
        )

    # Load and validate all files up front so we fail fast before auth.
    saved_accounts: list[tuple[Path, SavedScrape]] = []
    for path in files:
        try:
            saved = load_saved_scrape(path)
            saved_accounts.append((path, saved))
            logger.debug(
                "Loaded %s: %s, %d tx(s), balance=%s",
                path.name,
                saved.account_name,
                len(saved.transactions),
                saved.ending_balance,
            )
        except (ValueError, KeyError) as e:
            raise click.ClickException(f"Cannot load {path}: {e}") from e

    any_error = False

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

            for path, saved in saved_accounts:
                acct_name = saved.account_name
                if interactive:
                    console.rule(
                        f"[bold]{acct_name}[/bold] [dim]({path.name})[/dim]"
                    )
                else:
                    logger.info(
                        "--- Replaying %s (%s) ---", acct_name, path.name
                    )

                account = _ReplayAccount(saved)
                statement = _build_statement(account)

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

                # Must run before _fetch_existing so that any pending rows
                # resolved here show up in the dedup map as settled and are
                # not re-imported as new transactions.
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

                # Capture settled list now; used later to gate _mark_imported.
                settled_txs = [
                    tx for tx in statement.transactions if not tx.pending
                ]

                # Dedup window spans ALL transactions (settled + pending) so
                # that pending rows -- whose date is today -- are not outside
                # the fetch range and re-imported on every run.
                existing: dict[
                    tuple[str, str, str], list[tuple[str, str, str]]
                ] = {}
                existing_by_bank_id: dict[str, tuple[str, str, str]] = {}
                if statement.transactions:
                    dedup_start = min(
                        tx.transaction_date for tx in statement.transactions
                    )
                    dedup_end = max(
                        tx.transaction_date for tx in statement.transactions
                    )
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

                # BofA's web UI truncates long ACH descriptions with '...'.
                # Map them to the full version from a prior CSV import so the
                # (date, amount, description) dedup key matches.
                if existing:
                    statement = _resolve_truncated_descriptions(
                        statement, existing
                    )

                result = import_statement(
                    statement,
                    bank_account_id,
                    client,
                    user_timezone,
                    existing=existing,
                    existing_by_bank_id=existing_by_bank_id,
                    dry_run=dry_run,
                )

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
                        "Skipped (duplicates)",
                        f"[dim]{result.skipped}[/dim]",
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

    except AuthenticationError as e:
        raise click.ClickException(str(e)) from e
    except KeyboardInterrupt as e:
        raise click.Abort() from e

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
