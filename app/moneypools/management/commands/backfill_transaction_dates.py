"""
Re-derive transaction_date (and optionally posted_date) for existing
Transaction rows.

Normal run
----------
Walks every Transaction whose transaction_date equals its posted_date
(the initial backfill state -- not yet enriched) and attempts to parse
a purchase date from the raw_description.  Where a date is found within
the sanity window (0--7 days before posted_date) the transaction_date
field is updated.  Rows that cannot be improved are left unchanged.

This command is safe to run multiple times -- it only rewrites rows
where transaction_date == posted_date (i.e. rows not yet enriched).

--force
-------
Re-processes every Transaction (or every Transaction in the given
account), overwriting the previously-derived transaction_date.  Also
re-anchors posted_date and transaction_date to midnight in the owning
user's configured timezone so that display in the Vue app shows the
correct calendar date.

Use --force after:
* The user sets their timezone for the first time.
* Correcting a wrong timezone.
* Any previous run that stored dates as midnight UTC instead of midnight
  in the user's local timezone.

Usage:

    uv run python app/manage.py backfill_transaction_dates
    uv run python app/manage.py backfill_transaction_dates --account "Chase Checking"
    uv run python app/manage.py backfill_transaction_dates --dry-run
    uv run python app/manage.py backfill_transaction_dates --force
    uv run python app/manage.py backfill_transaction_dates --force --account a1b2c3
"""

# system imports
#
import logging
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

# 3rd party imports
#
from django.core.management.base import BaseCommand
from django.db import models

# Project imports
#
from moneypools.description_utils import parse_transaction_date
from moneypools.management.commands._budget_admin import resolve_account
from moneypools.models import Transaction

logger = logging.getLogger(__name__)


########################################################################
########################################################################
#
class Command(BaseCommand):
    """Re-derive transaction_date from raw_description + posted_date."""

    help = (
        "Re-derive transaction_date for existing Transaction rows.  "
        "Normal mode only processes rows where transaction_date == posted_date.  "
        "Use --force to re-process all rows and re-anchor dates to the "
        "owning user's configured timezone."
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
            help="Print what would change without writing to the database.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            default=False,
            help=(
                "Re-process all transactions, not just unenriched ones.  "
                "Re-anchors posted_date and transaction_date to midnight in "
                "the owning user's timezone.  Use after setting or correcting "
                "the user timezone."
            ),
        )

    ####################################################################
    #
    def handle(self, *args: Any, **options: Any) -> None:
        """
        Args:
            *args: Unused positional arguments.
            **options: Parsed CLI options (account, dry_run, force).
        """
        dry_run: bool = options["dry_run"]
        force: bool = options["force"]
        pattern: str | None = options["account"]
        account = resolve_account(pattern) if pattern else None

        if force:
            qs = Transaction.objects.select_related(
                "bank_account"
            ).prefetch_related("bank_account__owners")
        else:
            qs = (
                Transaction.objects.filter(
                    transaction_date=models.F("posted_date")
                )
                .select_related("bank_account")
                .prefetch_related("bank_account__owners")
            )

        if account:
            qs = qs.filter(bank_account=account)

        total = qs.count()
        prefix = "[DRY RUN] " if dry_run else ""
        scope = (
            f"in account '{account.name}' ({str(account.id)[:8]})"
            if account
            else "across all accounts"
        )
        mode = " (force -- all rows)" if force else " (unenriched rows only)"
        self.stdout.write(
            f"{prefix}Examining {total} transaction(s) {scope}{mode}."
        )

        updated = 0
        skipped = 0

        # Cache timezone per bank account to avoid repeated owner lookups.
        tz_cache: dict[int, str] = {}

        for tx in qs.iterator(chunk_size=500):
            acct_pk = tx.bank_account_id
            if acct_pk not in tz_cache:
                owner = tx.bank_account.owners.first()
                tz_cache[acct_pk] = owner.timezone if owner else "UTC"
            tz_name = tz_cache[acct_pk]
            tz = ZoneInfo(tz_name)

            # Use the UTC date from posted_date as the canonical calendar date.
            # For legacy rows (midnight UTC) this is the correct BofA date.
            # For new rows (midnight user-TZ stored as UTC) the UTC date is
            # also correct for US timezones because midnight PDT/PST is still
            # Oct 15 in UTC (it becomes Oct 15 at 07:00 or 08:00 UTC).
            posted_local_date = tx.posted_date.astimezone(UTC).date()

            derived_date = parse_transaction_date(
                tx.raw_description, posted_local_date
            )

            # Anchor both datetimes to midnight in the user's timezone.
            new_posted_dt = datetime(
                posted_local_date.year,
                posted_local_date.month,
                posted_local_date.day,
                tzinfo=tz,
            ).astimezone(UTC)
            new_tx_dt = datetime(
                derived_date.year,
                derived_date.month,
                derived_date.day,
                tzinfo=tz,
            ).astimezone(UTC)

            posted_unchanged = new_posted_dt == tx.posted_date.astimezone(UTC)
            tx_date_unchanged = new_tx_dt == tx.transaction_date.astimezone(UTC)

            if posted_unchanged and tx_date_unchanged:
                skipped += 1
                continue

            if dry_run:
                self.stdout.write(
                    f"  Would update {tx.id}: "
                    f"posted {tx.posted_date.date()} -> {new_posted_dt.date()}  "
                    f"tx_date {tx.transaction_date.date()} -> {new_tx_dt.date()}  "
                    f"tz={tz_name}  ({tx.raw_description[:50]})"
                )
            else:
                fields: dict[str, datetime] = {"transaction_date": new_tx_dt}
                if not posted_unchanged:
                    fields["posted_date"] = new_posted_dt
                Transaction.objects.filter(pk=tx.pk).update(**fields)
            updated += 1

        self.stdout.write(
            f"{'Would update' if dry_run else 'Updated'} {updated}, "
            f"skipped {skipped} (already correct)."
        )
