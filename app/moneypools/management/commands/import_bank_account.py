"""
Restore a bank account and all its related data from a JSON export.

Reads a file produced by 'export_bank_account' and recreates the Bank,
BankAccount, Budgets, Transactions, TransactionAllocations, and
InternalTransactions with their original UUIDs. The command is
idempotent: re-running on an already-imported dataset updates existing
rows rather than duplicating them.

Balance fields are restored exactly as exported; the service layer is
NOT invoked (which would re-compute balances from scratch). Run
'verify_balances' after import to confirm the invariant holds.

Linked transactions that reference UUIDs outside this export are set to
null; run 'relink_transactions' after importing all accounts if you need
cross-account links restored.

Usage:

    uv run python app/manage.py import_bank_account backup.json
    uv run python app/manage.py import_bank_account backup.json --dry-run
"""

# system imports
#
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

# 3rd party imports
#
import recurrence
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction
from djmoney.money import Money

# Project imports
#
from moneypools.models import (
    Bank,
    BankAccount,
    Budget,
    InternalTransaction,
    Transaction,
    TransactionAllocation,
)

User = get_user_model()


########################################################################
########################################################################
#
class Command(BaseCommand):
    help = (
        "Restore a bank account from a JSON export produced by "
        "export_bank_account. Idempotent: re-running updates existing rows."
    )

    ####################################################################
    #
    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "input",
            metavar="FILE",
            help="Path to the JSON export file.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Parse and validate the file but make no DB changes.",
        )

    ####################################################################
    #
    def handle(self, *args: Any, **options: Any) -> None:
        path: str = options["input"]
        dry_run: bool = options["dry_run"]

        with open(path) as fh:
            data: dict[str, Any] = json.load(fh)

        version = data.get("version")
        if version != 1:
            raise CommandError(
                f"Unsupported export version: {version!r}. "
                "Only version 1 is supported."
            )

        if dry_run:
            self.stdout.write(
                self.style.WARNING("Dry run -- no changes will be made.")
            )

        self.stdout.write(
            f"Importing: {data['bank_account']['name']}  "
            f"(exported {data.get('exported_at', 'unknown')})"
        )

        if dry_run:
            self._validate(data)
            self.stdout.write(self.style.SUCCESS("Dry run complete."))
            return

        with db_transaction.atomic():
            self._import(data)

    ####################################################################
    #
    def _validate(self, data: dict[str, Any]) -> None:
        """Warn about any missing owners or actors without aborting.

        Args:
            data: The parsed export dict.
        """
        for username in data["bank_account"]["owners"]:
            if not User.objects.filter(username=username).exists():
                self.stdout.write(
                    self.style.WARNING(
                        f"  WARNING: owner {username!r} not found -- "
                        "account will be imported without this owner"
                    )
                )
        known_actors = {
            itx["actor_username"]
            for itx in data.get("internal_transactions", [])
        }
        for username in known_actors:
            if not User.objects.filter(username=username).exists():
                self.stdout.write(
                    self.style.WARNING(
                        f"  WARNING: actor {username!r} not found -- "
                        "internal transactions for this actor will be skipped"
                    )
                )

    ####################################################################
    #
    def _import(self, data: dict[str, Any]) -> None:
        """Perform the full import inside an atomic block.

        Args:
            data: The parsed export dict.
        """
        stats: dict[str, int] = {
            "budgets": 0,
            "transactions": 0,
            "allocations": 0,
            "internal_transactions": 0,
        }

        # 1. Bank
        bank = _restore_bank(data["bank"])
        self.stdout.write(f"  Bank: {bank.name}")

        # 2. BankAccount (no unallocated_budget yet)
        account = _restore_account(data["bank_account"], bank)
        self.stdout.write(f"  Account: {account.name} ({account.id})")

        # 3. Owners
        owners = _resolve_users(data["bank_account"]["owners"])
        account.owners.set(owners)

        # 4. Budgets -- pass 1: create without fillup_goal
        budget_map: dict[str, Budget] = {}
        for bd in data["budgets"]:
            budget, _ = _restore_budget_pass1(bd, account)
            budget_map[bd["id"]] = budget
            stats["budgets"] += 1

        # 5. Budgets -- pass 2: wire fillup_goal, set unallocated_budget
        for bd in data["budgets"]:
            if bd.get("fillup_goal_id"):
                parent = budget_map[bd["id"]]
                child = budget_map.get(bd["fillup_goal_id"])
                if child is not None:
                    Budget.objects.filter(pkid=parent.pkid).update(
                        fillup_goal_id=child.id
                    )

        unalloc_id = data["bank_account"].get("unallocated_budget_id")
        if unalloc_id and unalloc_id in budget_map:
            BankAccount.objects.filter(pkid=account.pkid).update(
                unallocated_budget_id=budget_map[unalloc_id].id
            )
            account.refresh_from_db()

        # 6. Transactions -- pass 1: create without linked_transaction
        tx_map: dict[str, Transaction] = {}
        for td in data["transactions"]:
            tx = _restore_transaction(td, account)
            tx_map[td["id"]] = tx
            stats["transactions"] += 1

            # 7. Allocations for this transaction
            for ad in td.get("allocations", []):
                alloc_budget = budget_map.get(ad.get("budget_id", ""))
                _restore_allocation(ad, tx, alloc_budget)
                stats["allocations"] += 1

        # 8. Transactions -- pass 2: wire linked_transaction
        for td in data["transactions"]:
            linked_id = td.get("linked_transaction_id")
            if linked_id:
                tx = tx_map[td["id"]]
                linked = tx_map.get(linked_id)
                if linked is not None:
                    Transaction.objects.filter(pkid=tx.pkid).update(
                        linked_transaction_id=linked.id
                    )
                # If linked tx is in another account, leave null; run
                # relink_transactions afterwards to reconnect cross-account links.

        # 9. InternalTransactions
        for itxd in data.get("internal_transactions", []):
            if _restore_internal_tx(itxd, account, budget_map):
                stats["internal_transactions"] += 1
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"  Skipped InternalTransaction {itxd['id']}: "
                        f"actor {itxd['actor_username']!r} not found"
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"  Done -- "
                f"{stats['budgets']} budget(s), "
                f"{stats['transactions']} transaction(s), "
                f"{stats['allocations']} allocation(s), "
                f"{stats['internal_transactions']} internal transaction(s)"
            )
        )


########################################################################
########################################################################
#
def _money(d: dict[str, str] | None) -> Money | None:
    """Deserialize a Money dict from the export.

    Args:
        d: Dict with 'amount' and 'currency' keys, or None.

    Returns:
        A Money instance, or None.
    """
    if d is None:
        return None
    return Money(Decimal(d["amount"]), d["currency"])


####################################################################
#
def _money_required(d: dict[str, str] | None) -> Money:
    """Deserialize a required Money dict, defaulting to zero USD on None.

    Args:
        d: Dict with 'amount' and 'currency' keys, or None.

    Returns:
        A Money instance.
    """
    if d is None:
        return Money(Decimal("0.00"), "USD")
    return Money(Decimal(d["amount"]), d["currency"])


####################################################################
#
def _parse_dt(s: str | None) -> datetime | None:
    """Parse an ISO 8601 datetime string, returning None if absent.

    Args:
        s: ISO format datetime string, or None.

    Returns:
        A datetime instance, or None.
    """
    return datetime.fromisoformat(s) if s is not None else None


####################################################################
#
def _recurrence(s: str | None) -> Any:
    """Deserialize an RFC 5545 recurrence string.

    Args:
        s: RFC 5545 string from the export, or None.

    Returns:
        A recurrence.Recurrence object, or None.
    """
    if not s:
        return None
    try:
        return recurrence.deserialize(s)
    except Exception:
        return None


########################################################################
########################################################################
#
def _restore_bank(d: dict[str, Any]) -> Bank:
    """Find or create the Bank from export data.

    Looks up by UUID first; falls back to name. Updates mutable fields
    if the bank already exists.

    Args:
        d: Serialized Bank dict from the export.

    Returns:
        The Bank instance.
    """
    bank, _ = Bank.objects.update_or_create(
        id=UUID(d["id"]),
        defaults={
            "name": d["name"],
            "routing_number": d.get("routing_number"),
            "default_currency": d.get("default_currency", "USD"),
        },
    )
    return bank


####################################################################
#
def _restore_account(d: dict[str, Any], bank: Bank) -> BankAccount:
    """Find or create the BankAccount from export data.

    Restores all fields including exact balance values. The
    unallocated_budget FK is set to None and fixed in a later pass.

    Args:
        d: Serialized BankAccount dict from the export.
        bank: The parent Bank instance.

    Returns:
        The BankAccount instance (unallocated_budget not yet set).
    """
    group: Group | None = None
    if d.get("group"):
        group, _ = Group.objects.get_or_create(name=d["group"])

    account, created = BankAccount.objects.get_or_create(
        id=UUID(d["id"]),
        defaults={"bank": bank, "name": d["name"]},
    )

    account.bank = bank
    account.name = d["name"]
    account.account_type = d.get(
        "account_type", BankAccount.BankAccountType.CHECKING
    )
    account.currency = d.get("currency", "USD")
    account.account_number = d.get("account_number")
    account.link_aliases = d.get("link_aliases", [])
    account.group = group
    account.unallocated_budget = None

    posted = _money(d.get("posted_balance"))
    available = _money(d.get("available_balance"))
    if posted is not None:
        account.posted_balance = posted
    if available is not None:
        account.available_balance = available

    raw_imported_at = d.get("last_imported_at")
    account.last_imported_at = (
        datetime.fromisoformat(raw_imported_at) if raw_imported_at else None
    )
    raw_posted_through = d.get("last_posted_through")
    account.last_posted_through = (
        date.fromisoformat(raw_posted_through) if raw_posted_through else None
    )

    account.save()
    return account


####################################################################
#
def _resolve_users(usernames: list[str]) -> list[Any]:
    """Resolve a list of usernames to User objects, skipping missing ones.

    Args:
        usernames: List of username strings from the export.

    Returns:
        List of User instances that exist in the current DB.
    """
    users = []
    for username in usernames:
        try:
            users.append(User.objects.get(username=username))
        except User.DoesNotExist:
            pass
    return users


####################################################################
#
def _restore_budget_pass1(
    d: dict[str, Any], account: BankAccount
) -> tuple[Budget, bool]:
    """Find or create a Budget without setting fillup_goal.

    fillup_goal is set in a second pass after all budgets exist.

    Args:
        d: Serialized Budget dict from the export.
        account: The parent BankAccount.

    Returns:
        Tuple of (Budget instance, created bool).
    """
    budget, created = Budget.objects.get_or_create(
        id=UUID(d["id"]),
        defaults={
            "bank_account": account,
            "name": d["name"],
        },
    )

    budget.bank_account = account
    budget.name = d["name"]
    budget.budget_type = d.get("budget_type", Budget.BudgetType.GOAL)
    budget.funding_type = d.get("funding_type", Budget.FundingType.TARGET_DATE)
    budget.with_fillup_goal = d.get("with_fillup_goal", False)
    budget.fillup_goal = None

    balance = _money(d.get("balance"))
    target_balance = _money(d.get("target_balance"))
    funding_amount = _money(d.get("funding_amount"))

    if balance is not None:
        budget.balance = balance
    if target_balance is not None:
        budget.target_balance = target_balance
    if funding_amount is not None:
        budget.funding_amount = funding_amount

    budget.target_date = (
        date.fromisoformat(d["target_date"]) if d.get("target_date") else None
    )

    budget.archived = d.get("archived", False)
    budget.archived_at = (
        datetime.fromisoformat(d["archived_at"])
        if d.get("archived_at")
        else None
    )

    budget.paused = d.get("paused", False)
    budget.complete = d.get("complete", False)

    budget.last_funded_on = (
        date.fromisoformat(d["last_funded_on"])
        if d.get("last_funded_on")
        else None
    )
    budget.last_recurrence_on = (
        date.fromisoformat(d["last_recurrence_on"])
        if d.get("last_recurrence_on")
        else None
    )
    budget.memo = d.get("memo")
    budget.auto_spend = d.get("auto_spend", [])

    funding_sched = _recurrence(d.get("funding_schedule"))
    if funding_sched is not None:
        budget.funding_schedule = funding_sched

    recurrance_sched = _recurrence(d.get("recurrance_schedule"))
    budget.recurrance_schedule = recurrance_sched

    budget.save()
    return budget, created


####################################################################
#
def _restore_transaction(
    d: dict[str, Any], account: BankAccount
) -> Transaction:
    """Find or create a Transaction without setting linked_transaction.

    linked_transaction is wired in a second pass after all transactions
    in this export exist.

    Args:
        d: Serialized Transaction dict from the export.
        account: The parent BankAccount.

    Returns:
        The Transaction instance.
    """
    from datetime import datetime

    amount = _money_required(d.get("amount"))
    posted_date = datetime.fromisoformat(d["posted_date"])
    transaction_date = datetime.fromisoformat(d["transaction_date"])

    tx, _ = Transaction.objects.get_or_create(
        id=UUID(d["id"]),
        defaults={
            "bank_account": account,
            "amount": amount,
            "posted_date": posted_date,
            "transaction_date": transaction_date,
            "raw_description": d.get("raw_description", ""),
            "description": d.get("description") or d.get("raw_description", ""),
        },
    )

    tx.bank_account = account
    tx.transaction_type = d.get("transaction_type", "")
    tx.pending = d.get("pending", False)
    tx.memo = d.get("memo")
    tx.raw_description = d.get("raw_description", "")
    tx.description = d.get("description") or tx.raw_description
    tx.party = d.get("party")
    tx.linked_transaction = None

    posted_bal = _money(d.get("bank_account_posted_balance"))
    avail_bal = _money(d.get("bank_account_available_balance"))
    if posted_bal is not None:
        tx.bank_account_posted_balance = posted_bal
    if avail_bal is not None:
        tx.bank_account_available_balance = avail_bal

    tx.save()
    return tx


####################################################################
#
def _restore_allocation(
    d: dict[str, Any],
    tx: Transaction,
    budget: Budget | None,
) -> TransactionAllocation:
    """Find or create a TransactionAllocation.

    Args:
        d: Serialized allocation dict from the export.
        tx: The parent Transaction.
        budget: The Budget for this allocation, or None.

    Returns:
        The TransactionAllocation instance.
    """
    amount = _money_required(d.get("amount"))
    budget_balance = _money(d.get("budget_balance"))

    alloc, _ = TransactionAllocation.objects.get_or_create(
        id=UUID(d["id"]),
        defaults={
            "transaction": tx,
            "budget": budget,
            "amount": amount,
        },
    )

    alloc.transaction = tx
    alloc.budget = budget
    alloc.category = d.get("category", "Uncategorized:Unassigned")
    alloc.memo = d.get("memo")

    if budget_balance is not None:
        alloc.budget_balance = budget_balance

    alloc.save()
    return alloc


####################################################################
#
def _restore_internal_tx(
    d: dict[str, Any],
    account: BankAccount,
    budget_map: dict[str, Budget],
) -> bool:
    """Find or create an InternalTransaction.

    Args:
        d: Serialized InternalTransaction dict from the export.
        account: The parent BankAccount.
        budget_map: Map of budget UUID string -> Budget instance.

    Returns:
        True if the record was imported, False if skipped (actor missing).
    """
    try:
        actor = User.objects.get(username=d["actor_username"])
    except User.DoesNotExist:
        return False

    src_budget = budget_map.get(d["src_budget_id"])
    dst_budget = budget_map.get(d["dst_budget_id"])
    if src_budget is None or dst_budget is None:
        return False

    amount = _money_required(d.get("amount"))
    src_bal = _money(d.get("src_budget_balance"))
    dst_bal = _money(d.get("dst_budget_balance"))
    effective_date = _parse_dt(d.get("effective_date"))

    itx, _ = InternalTransaction.objects.get_or_create(
        id=UUID(d["id"]),
        defaults={
            "bank_account": account,
            "amount": amount,
            "src_budget": src_budget,
            "dst_budget": dst_budget,
            "actor": actor,
            "effective_date": effective_date,
        },
    )

    itx.bank_account = account
    itx.src_budget = src_budget
    itx.dst_budget = dst_budget
    itx.actor = actor
    if effective_date is not None:
        itx.effective_date = effective_date

    if src_bal is not None:
        itx.src_budget_balance = src_bal
    if dst_bal is not None:
        itx.dst_budget_balance = dst_bal

    itx.save()
    return True
