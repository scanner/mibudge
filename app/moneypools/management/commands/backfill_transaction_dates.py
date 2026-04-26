"""
Re-derive transaction_date for existing Transaction rows.

Walks every Transaction whose transaction_date equals its posted_date
(the initial backfill state) and attempts to parse a purchase date from
the raw_description.  Where a date is found within the sanity window
(0--7 days before posted_date) the transaction_date field is updated.
Rows that cannot be improved are left unchanged.

This command is safe to run multiple times -- it only rewrites rows
where transaction_date == posted_date (i.e. rows not yet enriched).

Usage:

    uv run python app/manage.py backfill_transaction_dates
    uv run python app/manage.py backfill_transaction_dates --account <uuid>
    uv run python app/manage.py backfill_transaction_dates --dry-run
"""

# system imports
#
import logging
from datetime import UTC, datetime
from typing import Any

# 3rd party imports
#
from django.core.management.base import BaseCommand
from django.db import models

# Project imports
#
from moneypools.description_utils import parse_transaction_date
from moneypools.models import Transaction

logger = logging.getLogger(__name__)


########################################################################
########################################################################
#
class Command(BaseCommand):
    """Re-derive transaction_date from raw_description + posted_date."""

    help = (
        "Re-derive transaction_date for rows where it still equals "
        "posted_date (i.e. rows not yet enriched by description parsing)."
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
            metavar="UUID",
            default=None,
            help="Restrict to a single bank account UUID.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Print what would change without writing to the database.",
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
        account_id: str | None = options["account"]

        qs = Transaction.objects.filter(
            transaction_date=models.F("posted_date")
        )
        if account_id:
            qs = qs.filter(bank_account__id=account_id)

        total = qs.count()
        self.stdout.write(
            f"{'[DRY RUN] ' if dry_run else ''}"
            f"Examining {total} transaction(s) "
            f"{'in account ' + account_id if account_id else 'across all accounts'}."
        )

        updated = 0
        skipped = 0

        for tx in qs.iterator(chunk_size=500):
            posted = tx.posted_date.astimezone(UTC).date()
            derived = parse_transaction_date(tx.raw_description, posted)
            if derived == posted:
                skipped += 1
                continue

            new_dt = datetime(
                derived.year, derived.month, derived.day, tzinfo=UTC
            )
            if not dry_run:
                Transaction.objects.filter(pk=tx.pk).update(
                    transaction_date=new_dt
                )
            else:
                self.stdout.write(
                    f"  Would update {tx.id}: "
                    f"{tx.transaction_date.date()} -> {derived} "
                    f"({tx.raw_description[:60]})"
                )
            updated += 1

        self.stdout.write(
            f"{'Would update' if dry_run else 'Updated'} {updated}, "
            f"skipped {skipped} (no parseable date found)."
        )
