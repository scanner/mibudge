"""
Export all data for a specific bank account to a portable JSON file.

The export includes the parent Bank, the BankAccount itself, all Budgets,
all Transactions with their TransactionAllocations, and all
InternalTransactions. Money values are serialized as dicts with 'amount'
and 'currency' keys. Recurrence fields are serialized as their RFC 5545
string representation. Image and document file fields export the stored
path only -- the files themselves are not included.

Usage:

    uv run python app/manage.py export_bank_account --account "Chase Checking"
    uv run python app/manage.py export_bank_account --account a1b2c3 --output backup.json
    uv run python app/manage.py export_bank_account --account a1b2c3 > backup.json
"""

# system imports
#
import json
import sys
from datetime import UTC, datetime
from typing import Any

# 3rd party imports
#
import recurrence
from django.core.management.base import BaseCommand

# Project imports
#
from moneypools.management.commands._budget_admin import resolve_account
from moneypools.models import (
    BankAccount,
    Budget,
    InternalTransaction,
    Transaction,
)


########################################################################
########################################################################
#
class Command(BaseCommand):
    help = "Export all data for a specific bank account to JSON."

    ####################################################################
    #
    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--account",
            required=True,
            metavar="PATTERN",
            help=(
                "Partial account name (substring, case-insensitive) or "
                "UUID prefix to identify the bank account."
            ),
        )
        parser.add_argument(
            "--output",
            default="-",
            metavar="FILE",
            help="Destination file path. Defaults to '-' (stdout).",
        )

    ####################################################################
    #
    def handle(self, *args: Any, **options: Any) -> None:
        account = resolve_account(options["account"])
        self.stderr.write(f"Exporting: {account}")

        budget_count = Budget.objects.filter(bank_account=account).count()
        tx_count = Transaction.objects.filter(bank_account=account).count()
        itx_count = InternalTransaction.objects.filter(
            bank_account=account
        ).count()
        self.stderr.write(
            f"  {budget_count} budgets, {tx_count} transactions, "
            f"{itx_count} internal transactions"
        )

        data = _build_export(account)

        output: str = options["output"]
        if output == "-":
            json.dump(data, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            with open(output, "w") as fh:
                json.dump(data, fh, indent=2)
                fh.write("\n")
            self.stderr.write(self.style.SUCCESS(f"Exported to {output}"))


########################################################################
########################################################################
#
def _money(value: Any) -> dict[str, str] | None:
    """Serialize a djmoney Money value.

    Args:
        value: A Money instance or None.

    Returns:
        Dict with 'amount' (string) and 'currency' (string), or None.
    """
    if value is None:
        return None
    return {"amount": str(value.amount), "currency": str(value.currency)}


####################################################################
#
def _recurrence(value: Any) -> str | None:
    """Serialize a django-recurrence field value.

    Args:
        value: A recurrence.Recurrence instance or None.

    Returns:
        RFC 5545 string, or None if the value is empty/None.
    """
    if value is None:
        return None
    try:
        serialized = recurrence.serialize(value)
    except Exception:
        serialized = str(value)
    return serialized.strip() or None


####################################################################
#
def _build_export(account: BankAccount) -> dict[str, Any]:
    """Assemble the full export dict for *account*.

    Args:
        account: The BankAccount to export.

    Returns:
        A JSON-serializable dict with all account data.
    """
    budgets = list(Budget.objects.filter(bank_account=account).order_by("pkid"))
    transactions = list(
        Transaction.objects.filter(bank_account=account)
        .prefetch_related("allocations__budget")
        .order_by("pkid")
    )
    internal_txs = list(
        InternalTransaction.objects.filter(bank_account=account)
        .select_related("src_budget", "dst_budget", "actor")
        .order_by("pkid")
    )

    return {
        "version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "bank": _serialize_bank(account.bank),
        "bank_account": _serialize_account(account),
        "budgets": [_serialize_budget(b) for b in budgets],
        "transactions": [_serialize_transaction(tx) for tx in transactions],
        "internal_transactions": [
            _serialize_internal_tx(itx) for itx in internal_txs
        ],
    }


####################################################################
#
def _serialize_bank(bank: Any) -> dict[str, Any]:
    return {
        "id": str(bank.id),
        "name": bank.name,
        "routing_number": bank.routing_number,
        "default_currency": bank.default_currency,
    }


####################################################################
#
def _serialize_account(account: BankAccount) -> dict[str, Any]:
    unalloc_id = (
        str(account.unallocated_budget.id)
        if account.unallocated_budget
        else None
    )
    owners = list(
        account.owners.values_list("username", flat=True).order_by("username")
    )
    group_name = account.group.name if account.group else None
    return {
        "id": str(account.id),
        "name": account.name,
        "account_type": account.account_type,
        "currency": account.currency,
        "account_number": account.account_number,
        "posted_balance": _money(account.posted_balance),
        "available_balance": _money(account.available_balance),
        "link_aliases": account.link_aliases,
        "owners": owners,
        "group": group_name,
        "unallocated_budget_id": unalloc_id,
        "last_imported_at": (
            account.last_imported_at.isoformat()
            if account.last_imported_at
            else None
        ),
        "last_posted_through": (
            account.last_posted_through.isoformat()
            if account.last_posted_through
            else None
        ),
    }


####################################################################
#
def _serialize_budget(b: Budget) -> dict[str, Any]:
    fillup_id = str(b.fillup_goal.id) if b.fillup_goal else None
    return {
        "id": str(b.id),
        "name": b.name,
        "budget_type": b.budget_type,
        "funding_type": b.funding_type,
        "balance": _money(b.balance),
        "funded_amount": _money(b.funded_amount),
        "target_balance": _money(b.target_balance),
        "funding_amount": _money(b.funding_amount),
        "target_date": b.target_date.isoformat() if b.target_date else None,
        "fillup_goal_id": fillup_id,
        "archived": b.archived,
        "archived_at": (b.archived_at.isoformat() if b.archived_at else None),
        "paused": b.paused,
        "complete": b.complete,
        "funding_schedule": _recurrence(b.funding_schedule),
        "recurrence_schedule": _recurrence(b.recurrence_schedule),
        "memo": b.memo,
        "auto_spend": b.auto_spend,
        "last_funded_on": b.last_funded_on.isoformat()
        if b.last_funded_on
        else None,
        "last_recurrence_on": (
            b.last_recurrence_on.isoformat() if b.last_recurrence_on else None
        ),
    }


####################################################################
#
def _serialize_transaction(tx: Transaction) -> dict[str, Any]:
    linked_id = str(tx.linked_transaction.id) if tx.linked_transaction else None
    allocations = [
        _serialize_allocation(a) for a in tx.allocations.all().order_by("pkid")
    ]
    return {
        "id": str(tx.id),
        "amount": _money(tx.amount),
        "posted_date": tx.posted_date.isoformat(),
        "transaction_date": tx.transaction_date.isoformat(),
        "transaction_type": tx.transaction_type,
        "pending": tx.pending,
        "memo": tx.memo,
        "raw_description": tx.raw_description,
        "description": tx.description,
        "party": tx.party,
        "bank_account_posted_balance": _money(tx.bank_account_posted_balance),
        "bank_account_available_balance": _money(
            tx.bank_account_available_balance
        ),
        "linked_transaction_id": linked_id,
        "allocations": allocations,
    }


####################################################################
#
def _serialize_allocation(a: Any) -> dict[str, Any]:
    budget_id = str(a.budget.id) if a.budget_id else None
    return {
        "id": str(a.id),
        "budget_id": budget_id,
        "amount": _money(a.amount),
        "budget_balance": _money(a.budget_balance),
        "category": a.category,
        "memo": a.memo,
    }


####################################################################
#
def _serialize_internal_tx(itx: InternalTransaction) -> dict[str, Any]:
    return {
        "id": str(itx.id),
        "amount": _money(itx.amount),
        "src_budget_id": str(itx.src_budget.id),
        "dst_budget_id": str(itx.dst_budget.id),
        "actor_username": itx.actor.username,
        "src_budget_balance": _money(itx.src_budget_balance),
        "dst_budget_balance": _money(itx.dst_budget_balance),
        "effective_date": itx.effective_date.isoformat(),
        "created_at": itx.created_at.isoformat(),
        "system_event_kind": itx.system_event_kind,
        "system_event_date": (
            itx.system_event_date.isoformat()
            if itx.system_event_date is not None
            else None
        ),
    }
