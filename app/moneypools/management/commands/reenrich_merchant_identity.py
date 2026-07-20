"""
Re-derive merchant identity (merchant_name, merchant_intermediary) and the
composed description for already-enriched Transaction rows, from their
stored `details` JSON -- no re-scrape needed.

Rows enriched before the merchant-identity cleanup pass
(service/merchant_enrichment.py) landed will have raw or platform-prefixed
names in merchant_name ("SQ *SHAKE SHACK", plain "COSTCO" for a gas
purchase). Since the raw provider dict has been stored verbatim on every
enriched Transaction since the enrichment pipeline shipped,
`apply_details(tx, tx.details, overwrite=True)` re-derives everything the
current code would have produced on first enrichment -- category
assignment is untouched (seeding only fires when category is NULL) and
user-entered location fields are preserved (enrichment only fills empty
location fields, even under overwrite).

Usage:

    uv run python app/manage.py reenrich_merchant_identity
    uv run python app/manage.py reenrich_merchant_identity --account "Chase Checking"
    uv run python app/manage.py reenrich_merchant_identity --dry-run
"""

# system imports
#
from typing import Any

# 3rd party imports
#
from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction
from django.db.models import QuerySet

# Project imports
#
from moneypools.management.commands._budget_admin import resolve_account
from moneypools.models import Transaction
from moneypools.service import transaction_details as transaction_details_svc


####################################################################
#
class _DryRunRollback(Exception):
    """Raised to unwind the enclosing atomic block on --dry-run."""


########################################################################
########################################################################
#
class Command(BaseCommand):
    """Re-run merchant-identity extraction on already-enriched rows."""

    help = (
        "Re-derive merchant_name/merchant_intermediary and the composed "
        "description for already-enriched transactions from their stored "
        "details JSON, with no re-scrape."
    )

    ####################################################################
    #
    def add_arguments(self, parser: Any) -> None:
        """
        Args:
            parser: ArgumentParser instance.
        """
        parser.add_argument(
            "--account",
            metavar="PATTERN",
            default=None,
            help=(
                "Restrict to a single bank account. Accepts a full UUID, "
                "UUID prefix/substring, or account name fragment "
                "(case-insensitive)."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Report what would change without writing to the database.",
        )

    ####################################################################
    #
    def handle(self, *args: Any, **options: Any) -> None:
        """
        Args:
            *args: Unused positional arguments.
            **options: Parsed CLI options (account, dry_run).
        """
        dry_run: bool = options["dry_run"]
        pattern: str | None = options["account"]
        account = resolve_account(pattern) if pattern else None

        qs = Transaction.objects.filter(details__isnull=False)
        if account:
            qs = qs.filter(bank_account=account)

        total = qs.count()
        prefix = "[DRY RUN] " if dry_run else ""
        scope = (
            f"in account '{account.name}'" if account else "across all accounts"
        )
        self.stdout.write(
            f"{prefix}Re-enriching {total} transaction(s) {scope}."
        )

        try:
            with db_transaction.atomic():
                changed = self._reenrich(qs)
                if dry_run:
                    raise _DryRunRollback
        except _DryRunRollback:
            pass

        self.stdout.write(
            f"{prefix}{changed} of {total} transaction(s) changed."
        )

    ####################################################################
    #
    def _reenrich(self, qs: QuerySet[Transaction]) -> int:
        """Re-apply stored details to every row in `qs`.

        Runs inside the caller's atomic block; a --dry-run wraps this
        in a savepoint that gets rolled back, so nothing here needs to
        know whether it will actually commit.

        Args:
            qs: Queryset of already-enriched Transaction rows.

        Returns:
            The number of rows whose merchant_name, merchant_intermediary,
            or description changed.
        """
        changed = 0
        for tx in qs.iterator(chunk_size=500):
            before = (
                tx.merchant_name,
                tx.merchant_intermediary,
                tx.description,
            )
            # qs is filtered to details__isnull=False.
            assert tx.details is not None
            transaction_details_svc.apply_details(
                tx, tx.details, overwrite=True, recompose_description=True
            )
            after = (tx.merchant_name, tx.merchant_intermediary, tx.description)
            if after != before:
                changed += 1
                self.stdout.write(f"  {tx.id}: {before[0]!r} -> {after[0]!r}")
        return changed
