"""
Re-run the opportunistic cross-account transaction linker over every
unlinked Transaction.

The link attempt normally runs in a Celery task fired from each
Transaction's post_save signal, so new transactions get linked
automatically. This command exists for the two cases where the
automatic path is not enough:

- the linking heuristic (or a BankAccount's ``link_aliases``) has
  been updated and we want the new rules applied to rows that were
  unlinkable at import time;
- a one-shot back-fill after an initial bulk import, where the first
  side of a pair was created before the second side existed and the
  second side's own save already tried (and succeeded at) linking,
  but some rows may still be stragglers.

Read-only with respect to account/budget balances. Only the
``linked_transaction`` FK on Transaction is touched.

Usage:

    uv run python app/manage.py relink_transactions
    uv run python app/manage.py relink_transactions --account <uuid>
"""

# system imports
from typing import Any

# 3rd party imports
from django.core.management.base import BaseCommand

# Project imports
from moneypools.linking import attempt_link
from moneypools.models import Transaction


########################################################################
########################################################################
#
class Command(BaseCommand):
    help = (
        "Attempt to link every unlinked Transaction to a counterpart on "
        "another account. Safe to re-run; idempotent."
    )

    ####################################################################
    #
    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--account",
            dest="account_id",
            help=(
                "Only consider transactions in the BankAccount with "
                "this UUID as the driving side of the link attempt."
            ),
        )

    ####################################################################
    #
    def handle(self, *args: Any, **options: Any) -> None:
        account_id: str | None = options["account_id"]

        qs = Transaction.objects.filter(
            linked_transaction__isnull=True
        ).order_by("transaction_date", "pkid")
        if account_id:
            qs = qs.filter(bank_account__id=account_id)

        attempted = 0
        linked = 0
        for tx in qs.iterator():
            # Re-read from the DB on each iteration so a link written
            # by a previous iteration's counterpart side is respected
            # (idempotence in attempt_link handles this regardless,
            # but skipping here avoids a pointless query).
            #
            tx.refresh_from_db(fields=["linked_transaction"])
            if tx.linked_transaction_id is not None:
                continue
            attempted += 1
            if attempt_link(tx) is not None:
                linked += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Attempted {attempted} transaction(s); linked {linked}."
            )
        )
