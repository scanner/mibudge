"""
Replay saved BofA scrape files into mibudge without logging in to BofA.

Loads one or more JSON files written by `import_bofa_live --save-dir`
and submits each one through the same scrape-sync endpoint the live
importer uses.  No browser, no BofA credentials -- just the saved
snapshot rolling forward into the database.

Files with per-transaction details (format_version 3, captured live or
via --save-only --details-all) also replay the enrichment: rows the
server reports in `details_needed` that carry saved details are POSTed
to the transaction-details endpoint -- no fetch budget applies since
no browser dialog is involved.

Useful for:
- Re-importing after fixing an issue without re-scraping
- Comparing coverage against CSV exports before committing an import
- Dry-running an import to preview what would be created

Usage::

    uv run python -m importers.import_bofa_saved \\
        saved/2026-05-15-103045-1234.json \\
        saved/2026-05-15-103045-5678.json \\
        [--dry-run] [--run-funding] [--verbose]
"""

# system imports
#
import logging
from datetime import UTC, datetime
from pathlib import Path

# 3rd party imports
#
import click
import yaml
from rich.console import Console
from rich.logging import RichHandler

# Project imports
#
from importers.bofa_categories import load_overlay_map
from importers.client import AuthenticationError
from importers.import_bofa_live import (
    SavedScrape,
    SavedTransaction,
    _build_sync_payload,
    _extract_last_four,
    _post_sync_scrape,
    _post_transaction_details,
    load_saved_scrape,
)
from importers.import_transactions import (
    _build_client,
    _resolve_account_by_query,
    _run_funding,
    load_importer_env,
)
from importers.theme import get_theme, theme_option

logger = logging.getLogger(__name__)


########################################################################
########################################################################
#
class _ReplayAccount:
    """Mock bofa_scraper Account backed by a `SavedScrape`.

    Implements the same interface as bofa_scraper's Account object so
    that `_build_sync_payload` can be called without a real browser
    session.
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
        "`import_bofa_live --save-dir` and submits each through the "
        "same scrape-sync endpoint the live importer uses.  mibudge "
        "credentials follow the same resolution order as the other "
        "importers.\n\n"
        "Useful for re-importing after a fix, dry-running to preview "
        "what would be created, or verifying coverage against CSV "
        "exports."
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
        "from any bank-specific 1Password URL option."
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
    help="Trust the mkcert root CA.  Required for local dev with mkcert TLS.",
)
@click.option(
    "--dry-run",
    "-n",
    is_flag=True,
    help=(
        "Show what would be imported without making any changes. "
        "Resolves accounts and builds the payload but does not POST."
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
    "--category-map",
    default=None,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help=(
        "YAML overlay for the built-in BofA-to-mibudge category map: "
        "normalized 'group:name' keys to mibudge category full names "
        "(or null for 'leave unassigned').  Overlay entries win over "
        "the built-ins.  [env var: MIBUDGE_CATEGORY_MAP]"
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
    email: str | None,
    password: str | None,
    api_key: str | None,
    vault_path: str | None,
    api_key_onepassword_url: str | None,
    ca_bundle: Path | None,
    trust_local_certs: bool,
    dry_run: bool,
    run_funding: bool,
    category_map: Path | None,
    verbose: bool,
    plain: bool,
    theme_name: str,
) -> None:
    """CLI entry point for replaying saved BofA scrape files."""
    # --- Output & logging setup ---
    console = Console(theme=get_theme(theme_name).rich, stderr=True)
    interactive = console.is_terminal and not plain
    _setup_logging(verbose, interactive, console=console)

    # --- Category translation setup ---
    # Mapping BofA's category vocabulary onto mibudge categories is
    # the importer's job (mibudge only understands its own category
    # full names).  The optional overlay extends/overrides the
    # built-in BOFA_CATEGORY_MAP; any BofA string found in neither is
    # collected here and reported at the end of the run.
    overlay: dict[str, str | None] | None = None
    if category_map is not None:
        try:
            overlay = load_overlay_map(category_map)
        except (ValueError, yaml.YAMLError) as e:
            raise click.ClickException(str(e)) from e
    unmapped_categories: set[str] = set()

    if dry_run and interactive:
        console.print(
            "[bold warning]DRY RUN[/bold warning] -- no changes will be made."
        )

    # --- Load & validate the saved scrape files ---
    # All files are parsed up front so a bad file fails the run before
    # any authentication or imports happen.
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

    # --- Connect and authenticate to mibudge ---
    try:
        with _build_client(
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
        ) as client:
            if interactive:
                with console.status("[bold]Authenticating to mibudge..."):
                    client.authenticate()
                console.print("[success]Authenticated to mibudge.[/success]")
            else:
                client.authenticate()
                logger.info("Authenticated to mibudge.")

            # Scraped transaction dates are naive; the sync payload
            # interprets them in the account owner's timezone.
            user_timezone: str = client.get("/api/v1/users/me/").get(
                "timezone", "UTC"
            )
            logger.info("User timezone: %s", user_timezone)

            # --- Replay each saved account snapshot ---
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

                # The mibudge bank account is located by the last-4
                # digits embedded in the BofA account name -- the only
                # stable identifier a saved snapshot carries.
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

                # The scrape's original scraped_at lives on the SavedScrape;
                # parse it back into a datetime for the payload.  Falls back
                # to the file's mtime then now() if the field is malformed
                # (shouldn't happen with a current-format file).
                try:
                    scraped_at = datetime.fromisoformat(saved.scraped_at)
                    if scraped_at.tzinfo is None:
                        scraped_at = scraped_at.replace(tzinfo=UTC)
                except ValueError:
                    scraped_at = datetime.now(UTC)

                # --- Submit the snapshot through scrape-sync ---
                # Same endpoint and payload as the live importer; the
                # server dedups against existing rows and reports
                # which posted rows still need details.
                payload, posted_count, pending_count = _build_sync_payload(
                    account, scraped_at, user_timezone
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

                # --- Replay saved per-transaction details (v3 files) ---
                # The payload's transaction order is exactly
                # saved.transactions (via _ReplayAccount), so the
                # server's details_needed indexes map straight back to
                # the saved rows.
                if report is not None:
                    details_items = []
                    for row in report.get("details_needed", []):
                        idx = row["index"]
                        if 0 <= idx < len(saved.transactions):
                            details = saved.transactions[idx].details
                            if details is not None:
                                details_items.append(
                                    {
                                        "transaction": row["transaction"],
                                        "details": details,
                                    }
                                )
                    if details_items:
                        if not _post_transaction_details(
                            client,
                            bank_account_id,
                            details_items,
                            acct_name,
                            console,
                            interactive,
                            overlay=overlay,
                            unmapped=unmapped_categories,
                        ):
                            any_error = True

                # Funding only fires when the snapshot contained at
                # least one posted transaction -- pending-only replays
                # do not advance last_posted_through and should not
                # trigger funding.
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

    # --- Run summary & exit status ---
    if unmapped_categories:
        listing = ", ".join(repr(c) for c in sorted(unmapped_categories))
        msg = (
            "BofA categories with no mapping (their transactions were "
            "left unassigned): "
            f"{listing}.  Add them to a --category-map overlay file or "
            "extend BOFA_CATEGORY_MAP in importers/bofa_categories.py."
        )
        if interactive:
            console.print(f"[warning]{msg}[/warning]")
        else:
            logger.warning("%s", msg)

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
