"""
Recompute all TransactionAllocation.budget_balance snapshots from scratch.

Run this once after deploying the effective_date fix to correct any
snapshots that were inflated by InternalTransactions being counted
multiple times.

For each budget that has allocations, the command finds the earliest
allocation (by transaction_date) and triggers a full forward
recalculation from that point.  Because the recalculation now uses
effective_date (not allocation.created_at) for ITx window boundaries,
the resulting snapshots will be correct regardless of when the
allocations or InternalTransactions were created.

Usage:

    uv run python app/manage.py recompute_running_balances
    uv run python app/manage.py recompute_running_balances --budget "Yearly Services"
    uv run python app/manage.py recompute_running_balances --account "Chase Checking"
"""

# system imports
#
from typing import Any

# 3rd party imports
#
from django.core.management.base import BaseCommand

# Project imports
#
from moneypools.management.commands._budget_admin import (
    resolve_account,
    resolve_budget,
)
from moneypools.models import Budget, TransactionAllocation
from moneypools.service import transaction_allocation as alloc_svc


########################################################################
########################################################################
#
class Command(BaseCommand):
    help = (
        "Recompute all budget_balance snapshots from scratch using the "
        "corrected effective_date-based InternalTransaction window logic."
    )

    ####################################################################
    #
    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--budget",
            default=None,
            metavar="PATTERN",
            help=(
                "Restrict to a single budget. Accepts a full UUID, "
                "UUID prefix/substring, or budget name fragment."
            ),
        )
        parser.add_argument(
            "--account",
            default=None,
            metavar="PATTERN",
            help=(
                "Restrict to budgets belonging to this bank account. "
                "Accepts a full UUID, UUID prefix/substring, or account "
                "name fragment (case-insensitive)."
            ),
        )

    ####################################################################
    #
    def handle(self, *args: Any, **options: Any) -> None:
        qs = Budget.objects.all()

        if options["account"]:
            account = resolve_account(options["account"])
            qs = qs.filter(bank_account=account)

        if options["budget"]:
            budget = resolve_budget(options["budget"])
            qs = qs.filter(pk=budget.pk)

        budgets = list(qs)
        self.stderr.write(
            f"Recomputing snapshots for {len(budgets)} budget(s)…"
        )

        updated = 0
        skipped = 0
        for budget in budgets:
            first = (
                TransactionAllocation.objects.filter(budget=budget)
                .order_by(
                    "transaction__transaction_date",
                    "transaction__created_at",
                    "created_at",
                )
                .select_related("transaction")
                .first()
            )
            if first is None:
                skipped += 1
                continue
            alloc_svc._recalculate_running_balances(budget, first.transaction)
            updated += 1
            self.stderr.write(f"  {budget.name}")

        self.stderr.write(
            self.style.SUCCESS(
                f"Done. Recomputed {updated} budget(s), skipped {skipped} (no allocations)."
            )
        )
