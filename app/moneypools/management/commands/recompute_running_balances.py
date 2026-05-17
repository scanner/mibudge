"""
Recompute all TransactionAllocation.budget_balance snapshots from scratch.

Run this once after deploying the effective_date fix to correct any
snapshots that were inflated by InternalTransactions being counted
multiple times.

For each budget that has allocations, the command finds the earliest
allocation (by transaction_date) and triggers a full forward
recalculation from that point.  InternalTransaction snapshots are then
recalculated from datetime.min so that ITxs whose effective_date
precedes the first allocation also get correct stored snapshots.

Usage:

    uv run python app/manage.py recompute_running_balances
    uv run python app/manage.py recompute_running_balances --budget "Yearly Services"
    uv run python app/manage.py recompute_running_balances --account "Chase Checking"
    uv run python app/manage.py recompute_running_balances --balances-only
"""

# system imports
#
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from django.core.management.base import BaseCommand

# 3rd party imports
#
from django.db.models import Sum
from django.db.models.functions import Coalesce
from djmoney.money import Money

# Project imports
#
from moneypools.management.commands._budget_admin import (
    resolve_account,
    resolve_budget,
)
from moneypools.models import (
    BankAccount,
    Budget,
    Transaction,
    TransactionAllocation,
)
from moneypools.service import transaction_allocation as alloc_svc


########################################################################
########################################################################
#
class Command(BaseCommand):
    help = (
        "Recompute all budget_balance snapshots from scratch using the "
        "corrected effective_date-based InternalTransaction window logic. "
        "Also recomputes BankAccount.posted_balance and available_balance "
        "from budget and pending-transaction sums."
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
        parser.add_argument(
            "--balances-only",
            action="store_true",
            help=(
                "Skip budget snapshot recomputation; only fix "
                "BankAccount.posted_balance and available_balance."
            ),
        )

    ####################################################################
    #
    def _recompute_account_balance(self, account: BankAccount) -> bool:
        """
        Recompute posted_balance and available_balance for one account.

        Invariants:
          available_balance == sum(budget.balance)
            -- every dollar is in exactly one budget, including pending
               transaction allocations.
          posted_balance == available_balance - sum(pending tx amounts)
            -- pending transactions affect budgets but not posted_balance.

        Returns True if either balance changed.
        """
        currency = account.currency

        available = Decimal(
            Budget.objects.filter(bank_account=account).aggregate(
                total=Coalesce(Sum("balance"), Decimal("0"))
            )["total"]
        )
        pending_sum = Decimal(
            Transaction.objects.filter(
                bank_account=account, pending=True
            ).aggregate(total=Coalesce(Sum("amount"), Decimal("0")))["total"]
        )
        posted = available - pending_sum

        new_available = Money(available, currency)
        new_posted = Money(posted, currency)

        if (
            account.available_balance == new_available
            and account.posted_balance == new_posted
        ):
            return False

        account.available_balance = new_available
        account.posted_balance = new_posted
        account.save()
        return True

    ####################################################################
    #
    def handle(self, *args: Any, **options: Any) -> None:
        qs = Budget.objects.all()
        accounts_qs = BankAccount.objects.all()

        if options["account"]:
            account = resolve_account(options["account"])
            qs = qs.filter(bank_account=account)
            accounts_qs = accounts_qs.filter(pk=account.pk)

        if options["budget"]:
            budget = resolve_budget(options["budget"])
            qs = qs.filter(pk=budget.pk)

        # --- Budget snapshot recomputation ---
        if not options["balances_only"]:
            budgets = list(qs)
            self.stderr.write(
                f"Recomputing snapshots for {len(budgets)} budget(s)..."
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
                alloc_svc.recalculate_from_transaction(
                    budget, first.transaction
                )
                # recalculate_from_transaction only fixes ITx snapshots from
                # first.transaction.transaction_date forward.  ITxs whose
                # effective_date precedes the first allocation are accounted
                # for in the balance baseline but their stored snapshots are
                # never rewritten.  Calling from datetime.min covers them.
                alloc_svc.recalculate_itx_snapshots_from_dt(
                    budget, datetime.min.replace(tzinfo=UTC)
                )
                updated += 1
                self.stderr.write(f"  {budget.name}")

            self.stderr.write(
                self.style.SUCCESS(
                    f"Done. Recomputed {updated} budget(s), skipped {skipped} (no allocations)."
                )
            )

        # --- Bank account balance recomputation ---
        accounts = list(accounts_qs)
        self.stderr.write(
            f"Recomputing bank account balances for {len(accounts)} account(s)..."
        )
        acct_updated = 0
        for account in accounts:
            changed = self._recompute_account_balance(account)
            if changed:
                acct_updated += 1
                self.stderr.write(
                    f"  updated: {account.name} "
                    f"posted={account.posted_balance} "
                    f"available={account.available_balance}"
                )

        self.stderr.write(
            self.style.SUCCESS(
                f"Done. Updated {acct_updated} account balance(s)."
            )
        )
