"""
Audit the core balance invariant: for every BankAccount, the sum of all
its Budget balances must equal the account's posted_balance.

Every dollar in a BankAccount is accounted for by some Budget (with the
auto-created "Unallocated" budget catching anything not explicitly
assigned). Signals maintain this invariant incrementally on every
Transaction, InternalTransaction, and TransactionAllocation save/delete.
A drift between the two sides indicates a bug in signal handling, a
botched bulk operation (bulk_create/bulk_update bypass signals), or a
corrupt import.

This command is read-only: it never mutates balances. The intended
workflow on a mismatch is to investigate the offending account, fix the
underlying cause, then re-run to confirm.

Usage:

    uv run python app/manage.py verify_balances
    uv run python app/manage.py verify_balances --account <uuid>
    uv run python app/manage.py verify_balances --tolerance 0.01

Exits non-zero when any account fails the check so the command can be
wired into CI or a periodic Celery task.
"""

# system imports
from decimal import Decimal
from typing import Any

# 3rd party imports
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Sum

# Project imports
from moneypools.models import BankAccount, Budget


########################################################################
########################################################################
#
class Command(BaseCommand):
    help = (
        "Verify that sum(budget.balance) == posted_balance for every "
        "BankAccount. Exits non-zero if any account is out of balance."
    )

    ####################################################################
    #
    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--account",
            dest="account_id",
            help="Only check the BankAccount with this UUID.",
        )
        parser.add_argument(
            "--tolerance",
            type=Decimal,
            default=Decimal("0.00"),
            help=(
                "Absolute difference below which an account is still "
                "considered balanced. Default: 0.00 (exact match)."
            ),
        )

    ####################################################################
    #
    def handle(self, *args: Any, **options: Any) -> None:
        account_id: str | None = options["account_id"]
        tolerance: Decimal = options["tolerance"]

        qs = BankAccount.objects.all().order_by("name")
        if account_id:
            qs = qs.filter(id=account_id)
            if not qs.exists():
                raise CommandError(
                    f"No BankAccount found with id={account_id!r}."
                )

        failures: list[tuple[BankAccount, Decimal, Decimal, Decimal]] = []
        total_checked = 0

        for account in qs:
            total_checked += 1
            budget_sum: Decimal = Budget.objects.filter(
                bank_account=account
            ).aggregate(total=Sum("balance"))["total"] or Decimal("0.00")
            posted: Decimal = account.posted_balance.amount
            delta = (posted - budget_sum).quantize(Decimal("0.01"))

            if abs(delta) <= tolerance:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"PASS  {account.name} ({str(account.id)[:8]}): "
                        f"posted={posted}  budgets={budget_sum}  delta={delta}"
                    )
                )
            else:
                failures.append((account, posted, budget_sum, delta))
                self.stdout.write(
                    self.style.ERROR(
                        f"FAIL  {account.name} ({str(account.id)[:8]}): "
                        f"posted={posted}  budgets={budget_sum}  delta={delta}"
                    )
                )

        self.stdout.write("")
        self.stdout.write(
            f"Checked {total_checked} account(s); {len(failures)} failed."
        )

        if failures:
            # Re-dump per-budget breakdown for each failing account so
            # the operator has something actionable to chase down.
            self.stdout.write("")
            self.stdout.write("Per-budget breakdown for failing accounts:")
            for account, posted, budget_sum, delta in failures:
                self.stdout.write("")
                self.stdout.write(
                    f"  {account.name} ({str(account.id)[:8]})  "
                    f"posted={posted}  budgets={budget_sum}  delta={delta}"
                )
                for budget in Budget.objects.filter(
                    bank_account=account
                ).order_by("name"):
                    archived_tag = " [archived]" if budget.archived else ""
                    self.stdout.write(
                        f"    {budget.balance.amount:>12}  "
                        f"{budget.name}{archived_tag}"
                    )
            raise CommandError(
                f"{len(failures)} BankAccount(s) out of balance."
            )
