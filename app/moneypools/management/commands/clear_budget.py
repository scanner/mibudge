"""
Clear a budget by reassigning all its transaction allocations to unallocated
and reversing all its internal transactions, leaving it with a zero balance.

This is a destructive administrative command intended for development and data
correction only.  The correct end-user path is to archive a budget, which
preserves its transaction history.

What this command does (in order):

  1. For every Transaction that has an allocation to this budget (or its
     fill-up goal), calls transaction_svc.split() with a splits dict that
     omits the budget.  split() assigns the freed portion to the account's
     unallocated budget and updates all budget_balance snapshots.

  2. Reverses all InternalTransactions involving this budget (or its fill-up
     goal) in reverse chronological order via internal_transaction_svc.delete(),
     which restores both sides' balances before removing each row.

After these two steps the budget has balance=0 and no associated transactions
or internal transactions.

With --delete, also deletes the budget row (and its fill-up goal child if any)
once it has been cleared.

By default the command runs as a dry run and prints a summary of what it
would do.  Pass --execute to commit the changes.

Usage:

    uv run python app/manage.py clear_budget --budget "Sneakers"
    uv run python app/manage.py clear_budget --budget <uuid> --execute
    uv run python app/manage.py clear_budget --budget "Sneakers" --account "Chase" --execute
    uv run python app/manage.py clear_budget --budget "Sneakers" --delete --execute
"""

# system imports
#
import sys
from typing import Any

# 3rd party imports
#
from django.core.management.base import BaseCommand, CommandError

# Project imports
#
from moneypools.management.commands._budget_admin import (
    count_allocations,
    count_internal_transactions,
    reassign_allocations,
    resolve_account,
    resolve_budget,
    reverse_internal_transactions,
    system_user,
)
from moneypools.models import BankAccount, Budget
from moneypools.service import budget as budget_svc


########################################################################
########################################################################
#
class Command(BaseCommand):
    help = (
        "Clear a budget: reassign its transaction allocations to unallocated "
        "and reverse its internal transactions, leaving it with a zero balance.  "
        "Pass --delete to also remove the budget row."
    )

    ####################################################################
    #
    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--budget",
            required=True,
            metavar="PATTERN",
            help=(
                "Partial budget name (substring, case-insensitive) or "
                "UUID prefix to identify the budget."
            ),
        )
        parser.add_argument(
            "--account",
            default=None,
            metavar="PATTERN",
            help=(
                "Optional: restrict the budget search to a specific bank "
                "account (partial name or UUID prefix)."
            ),
        )
        parser.add_argument(
            "--delete",
            action="store_true",
            default=False,
            help="Also delete the budget row after clearing it.",
        )
        parser.add_argument(
            "--execute",
            action="store_true",
            default=False,
            help=(
                "Actually perform the operation.  Without this flag the "
                "command runs as a dry run and only prints what it would do."
            ),
        )

    ####################################################################
    #
    def handle(self, *args: Any, **options: Any) -> None:
        account_pattern: str | None = options["account"]
        budget_pattern: str = options["budget"]
        also_delete: bool = options["delete"]
        execute: bool = options["execute"]

        account: BankAccount | None = None
        if account_pattern:
            account = resolve_account(account_pattern)

        budget = resolve_budget(budget_pattern, account)

        if budget.bank_account.unallocated_budget_id == budget.id:
            raise CommandError("Cannot clear the unallocated budget.")

        unallocated = budget.bank_account.unallocated_budget
        if unallocated is None:
            raise CommandError(
                "Account has no unallocated budget; cannot proceed."
            )

        # Collect stats for the dry-run report.
        alloc_count, tx_count = count_allocations(budget)
        itx_count = count_internal_transactions(budget)

        fillup: Budget | None = None
        fillup_alloc_count = 0
        fillup_tx_count = 0
        fillup_itx_count = 0
        if budget.fillup_goal_id:
            fillup = Budget.objects.get(id=budget.fillup_goal_id)
            fillup_alloc_count, fillup_tx_count = count_allocations(fillup)
            fillup_itx_count = count_internal_transactions(fillup)

        balance = budget.balance
        fillup_balance = fillup.balance if fillup else None

        # Warn if this budget is itself someone else's fill-up goal.
        parent_recurring = Budget.objects.filter(fillup_goal=budget).first()

        self.stderr.write(f"Budget:       {budget.name}  ({budget.id})")
        self.stderr.write(f"Account:      {budget.bank_account.name}")
        self.stderr.write(f"Type:         {budget.get_budget_type_display()}")
        self.stderr.write(f"Balance:      {balance}")
        self.stderr.write(
            f"Allocations:  {alloc_count} rows across {tx_count} transaction(s)"
        )
        self.stderr.write(f"Internal txs: {itx_count}")
        if fillup:
            self.stderr.write(
                f"Fill-up goal: {fillup.name}  balance={fillup_balance}  "
                f"allocations={fillup_alloc_count} across {fillup_tx_count} tx(s)  "
                f"internal txs={fillup_itx_count}"
            )
        if parent_recurring:
            self.stderr.write(
                self.style.WARNING(
                    f"WARNING: this budget is the fill-up goal for "
                    f"'{parent_recurring.name}' ({parent_recurring.id}).  "
                    f"Clearing it will zero its balance; if --delete is also "
                    f"passed, the parent's fillup_goal FK will be set to NULL."
                )
            )
        if also_delete:
            self.stderr.write("Action:       clear then DELETE")
        else:
            self.stderr.write("Action:       clear only (budget row kept)")

        if not execute:
            self.stderr.write(
                self.style.WARNING(
                    "\nDry run -- no changes made.  Pass --execute to proceed."
                )
            )
            return

        # Confirmation prompt when running interactively.
        if sys.stdin.isatty():
            if also_delete:
                msg = (
                    f"\nThis will clear all allocations and internal transactions "
                    f"for '{budget.name}', then permanently delete it."
                )
            else:
                msg = (
                    f"\nThis will clear all allocations and reverse all internal "
                    f"transactions for '{budget.name}'.  The budget row will remain "
                    f"with a zero balance."
                )
            self.stderr.write(self.style.WARNING(msg))
            answer = input("Type 'yes' to confirm: ").strip().lower()
            if answer != "yes":
                self.stderr.write("Aborted.")
                return

        actor = system_user()

        # Step 1: reassign allocations (fill-up first, then main budget).
        if fillup is not None and fillup_alloc_count > 0:
            self.stderr.write(
                f"Reassigning {fillup_alloc_count} fill-up allocation(s)…"
            )
            n = reassign_allocations(fillup)
            self.stderr.write(f"  Done ({n} allocation(s) moved).")

        if alloc_count > 0:
            self.stderr.write(
                f"Reassigning {alloc_count} allocation(s) across "
                f"{tx_count} transaction(s)…"
            )
            n = reassign_allocations(budget)
            self.stderr.write(f"  Done ({n} allocation(s) moved).")

        # Step 2: reverse internal transactions (main budget first so recur
        # events are undone before the fill-up's fund events are reversed).
        if itx_count > 0:
            self.stderr.write(f"Reversing {itx_count} internal transaction(s)…")
            n = reverse_internal_transactions(budget)
            self.stderr.write(f"  Done ({n} reversed).")

        if fillup is not None and fillup_itx_count > 0:
            # Re-count: recur events involving the fill-up were already deleted
            # above when we reversed the main budget's ITXs.
            remaining = count_internal_transactions(fillup)
            if remaining > 0:
                self.stderr.write(
                    f"Reversing {remaining} fill-up internal transaction(s)…"
                )
                n = reverse_internal_transactions(fillup)
                self.stderr.write(f"  Done ({n} reversed).")

        if also_delete:
            # budget_svc.delete() nulls the fillup_goal FK, deletes the
            # fill-up child, and deletes the budget row.  Balance is already
            # zero so no money movement is needed.
            budget_svc.delete(budget, actor)
            self.stderr.write(
                self.style.SUCCESS(f"Cleared and deleted '{budget.name}'.")
            )
        else:
            self.stderr.write(
                self.style.SUCCESS(
                    f"Cleared '{budget.name}'.  "
                    f"Funds returned to '{unallocated.name}'."
                )
            )
