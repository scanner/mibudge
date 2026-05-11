"""
Create or update budgets from a YAML definition file.

Each run is idempotent: budgets with an explicit 'id' that already exist
in the database are updated in-place; budgets whose 'id' is absent receive
a fresh UUID on first run (and subsequent runs cannot match them by name).

Usage:

    uv run python app/manage.py define_budgets budgets.yaml
    uv run python app/manage.py define_budgets budgets.yaml --dry-run

YAML format:

    bank_account: "Scanner's Checking"   # name fragment or full UUID

    budgets:
      - name: Emergency Fund
        id: "7c4f9a2b-..."               # optional; omit to auto-generate
        type: goal                        # goal | recurring | capped
        funding_type: target_date         # target_date | fixed_amount
        target_balance: "5000.00"
        target_date: 2026-12-31           # goal + target_date only
        funding_schedule: "RRULE:FREQ=MONTHLY;BYMONTHDAY=1"
        memo: "3-month emergency fund"    # optional

      - name: Groceries
        id: "a1b2c3d4-..."
        type: recurring
        funding_type: fixed_amount
        target_balance: "400.00"
        funding_amount: "100.00"          # required for fixed_amount
        funding_schedule: "RRULE:FREQ=MONTHLY;BYMONTHDAY=1"
        recurrence_schedule: "RRULE:FREQ=MONTHLY;BYMONTHDAY=1"
        with_fillup_goal: true
        paused: false

See the RFC 5545 spec for RRULE syntax.  Dry-run mode prints the next
scheduled dates for each rule so you can confirm the schedule is correct.
"""

# system imports
#
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

# 3rd party imports
#
import recurrence
import yaml
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction
from djmoney.money import Money

# Project imports
#
from moneypools.models import BankAccount, Budget
from moneypools.service import budget as budget_svc

from ._budget_admin import resolve_account

########################################################################
########################################################################
#
_BUDGET_TYPE_MAP: dict[str, str] = {
    "goal": Budget.BudgetType.GOAL,
    "recurring": Budget.BudgetType.RECURRING,
    "capped": Budget.BudgetType.CAPPED,
    "associated_fillup_goal": Budget.BudgetType.ASSOCIATED_FILLUP_GOAL,
    # also accept the raw single-letter model codes
    Budget.BudgetType.GOAL: Budget.BudgetType.GOAL,
    Budget.BudgetType.RECURRING: Budget.BudgetType.RECURRING,
    Budget.BudgetType.CAPPED: Budget.BudgetType.CAPPED,
    Budget.BudgetType.ASSOCIATED_FILLUP_GOAL: Budget.BudgetType.ASSOCIATED_FILLUP_GOAL,
}

_FUNDING_TYPE_MAP: dict[str, str] = {
    "target_date": Budget.FundingType.TARGET_DATE,
    "fixed_amount": Budget.FundingType.FIXED_AMOUNT,
    Budget.FundingType.TARGET_DATE: Budget.FundingType.TARGET_DATE,
    Budget.FundingType.FIXED_AMOUNT: Budget.FundingType.FIXED_AMOUNT,
}

_BUDGET_TYPE_LABELS: dict[str, str] = {
    Budget.BudgetType.GOAL: "goal",
    Budget.BudgetType.RECURRING: "recurring",
    Budget.BudgetType.CAPPED: "capped",
    Budget.BudgetType.ASSOCIATED_FILLUP_GOAL: "associated_fillup_goal",
}

_FUNDING_TYPE_LABELS: dict[str, str] = {
    Budget.FundingType.TARGET_DATE: "target_date",
    Budget.FundingType.FIXED_AMOUNT: "fixed_amount",
}


########################################################################
########################################################################
#
class Command(BaseCommand):
    help = (
        "Create or update budgets from a YAML definition file.  "
        "Idempotent when budgets specify an 'id' field."
    )

    ####################################################################
    #
    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "input",
            metavar="FILE",
            help="Path to the YAML budget definition file.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Validate and preview actions without making DB changes.",
        )

    ####################################################################
    #
    def handle(self, *args: Any, **options: Any) -> None:
        path: str = options["input"]
        dry_run: bool = options["dry_run"]

        with open(path) as fh:
            raw = yaml.safe_load(fh)

        if not isinstance(raw, dict):
            raise CommandError("YAML root must be a mapping.")

        account_pattern = raw.get("bank_account")
        if not account_pattern:
            raise CommandError("YAML must include a 'bank_account' key.")

        account = resolve_account(str(account_pattern))
        self.stdout.write(f"Account: {account.name}  ({account.id})")

        raw_budgets = raw.get("budgets")
        if not raw_budgets:
            raise CommandError("YAML must include a 'budgets' list.")
        if not isinstance(raw_budgets, list):
            raise CommandError("'budgets' must be a YAML list.")

        # Parse and validate all entries before touching the DB.
        #
        entries = [
            _parse_entry(b, idx, account) for idx, b in enumerate(raw_budgets)
        ]
        _check_duplicate_ids(entries)

        if dry_run:
            self.stdout.write(
                self.style.WARNING("Dry run -- no changes will be made.")
            )
            self._print_plan(entries, account)
            self.stdout.write(self.style.SUCCESS("Dry run complete."))
            return

        with db_transaction.atomic():
            created, updated = self._apply(entries, account)

        self.stdout.write(
            self.style.SUCCESS(f"Done -- {created} created, {updated} updated.")
        )

    ####################################################################
    #
    def _print_plan(
        self, entries: list[dict[str, Any]], account: BankAccount
    ) -> None:
        """Print a human-readable preview of what would be created/updated.

        Args:
            entries: Normalized budget entry dicts from _parse_entry().
            account: The resolved BankAccount.
        """
        for entry in entries:
            uid = entry.get("id")
            action = "UPDATE" if _budget_exists(uid) else "CREATE"
            label = self.style.NOTICE(action)

            budget_type = _BUDGET_TYPE_LABELS.get(
                entry["budget_type"], entry["budget_type"]
            )
            funding_type = _FUNDING_TYPE_LABELS.get(
                entry["funding_type"], entry["funding_type"]
            )

            self.stdout.write(
                f"\n  {label}  {entry['name']}"
                f"  [{budget_type} / {funding_type}]"
            )
            if uid:
                self.stdout.write(f"    id:             {uid}")
            else:
                self.stdout.write("    id:             (auto-generated)")
            self.stdout.write(f"    target_balance: {entry['target_balance']}")
            if entry.get("funding_amount") is not None:
                self.stdout.write(
                    f"    funding_amount: {entry['funding_amount']}"
                )
            if entry.get("target_date"):
                self.stdout.write(f"    target_date:    {entry['target_date']}")
            if entry.get("with_fillup_goal"):
                self.stdout.write("    with_fillup_goal: true")
            if entry.get("paused"):
                self.stdout.write("    paused: true")
            if entry.get("memo"):
                self.stdout.write(f"    memo:           {entry['memo']}")

            sched = entry.get("_funding_schedule_obj")
            if sched:
                occurrences = _next_occurrences(sched)
                if occurrences:
                    dates_str = ", ".join(str(d) for d in occurrences)
                    self.stdout.write(f"    funding_schedule next: {dates_str}")

            rsched = entry.get("_recurrence_schedule_obj")
            if rsched:
                occurrences = _next_occurrences(rsched)
                if occurrences:
                    dates_str = ", ".join(str(d) for d in occurrences)
                    self.stdout.write(
                        f"    recurrence_schedule next: {dates_str}"
                    )

    ####################################################################
    #
    def _apply(
        self,
        entries: list[dict[str, Any]],
        account: BankAccount,
    ) -> tuple[int, int]:
        """Create or update budgets from parsed entries.

        Args:
            entries: Normalized budget entry dicts from _parse_entry().
            account: The resolved BankAccount.

        Returns:
            Tuple of (created_count, updated_count).
        """
        created = 0
        updated = 0

        for entry in entries:
            uid = entry.get("id")
            existing = _get_budget(uid)

            # Build the kwargs dict for create/update, excluding
            # internal keys used only by this command.
            #
            kwargs: dict[str, Any] = {}
            if entry.get("_funding_schedule_obj") is not None:
                kwargs["funding_schedule"] = entry["_funding_schedule_obj"]
            if entry.get("_recurrence_schedule_obj") is not None:
                kwargs["recurrence_schedule"] = entry[
                    "_recurrence_schedule_obj"
                ]
            for field in (
                "target_date",
                "funding_amount",
                "with_fillup_goal",
                "paused",
                "memo",
            ):
                if field in entry:
                    kwargs[field] = entry[field]

            if existing is None:
                if uid is not None:
                    kwargs["id"] = uid
                budget_svc.create(
                    bank_account=account,
                    name=entry["name"],
                    budget_type=entry["budget_type"],
                    funding_type=entry["funding_type"],
                    target_balance=entry["target_balance"],
                    **kwargs,
                )
                self.stdout.write(
                    f"  Created: {entry['name']}"
                    + (f"  ({uid})" if uid else "")
                )
                created += 1
            else:
                changes: dict[str, Any] = {
                    "name": entry["name"],
                    "funding_type": entry["funding_type"],
                    "target_balance": entry["target_balance"],
                    **kwargs,
                }
                budget_svc.update(existing, **changes)
                self.stdout.write(
                    f"  Updated: {entry['name']}  ({existing.id})"
                )
                updated += 1

        return created, updated


########################################################################
########################################################################
#
def _parse_entry(
    raw: dict[str, Any], idx: int, account: BankAccount
) -> dict[str, Any]:
    """Parse and validate one budget entry from the YAML.

    Args:
        raw: Raw YAML mapping for a single budget.
        idx: Zero-based position in the 'budgets' list (for error messages).
        account: The resolved BankAccount (used for currency defaults).

    Returns:
        Normalized dict ready for _apply().

    Raises:
        CommandError: On any validation failure.
    """
    label = f"budgets[{idx}]"

    name = raw.get("name")
    if not name:
        raise CommandError(f"{label}: 'name' is required.")

    label = f"budgets[{idx}] ({name!r})"

    # Optional UUID; if provided, must be a valid UUID string.
    #
    uid: UUID | None = None
    raw_id = raw.get("id")
    if raw_id is not None:
        try:
            uid = UUID(str(raw_id))
        except ValueError as exc:
            raise CommandError(
                f"{label}: 'id' is not a valid UUID: {raw_id!r}"
            ) from exc

    budget_type = _normalize_type(raw.get("type", "goal"), label)
    funding_type = _normalize_funding_type(
        raw.get("funding_type", "target_date"), label
    )

    # target_balance
    #
    currency = account.currency or "USD"
    raw_target = raw.get("target_balance")
    if raw_target is None:
        raise CommandError(f"{label}: 'target_balance' is required.")
    target_balance = _parse_money(raw_target, currency, label, "target_balance")

    # funding_amount (required for fixed_amount funding type)
    #
    funding_amount: Money | None = None
    raw_fa = raw.get("funding_amount")
    if raw_fa is not None:
        funding_amount = _parse_money(raw_fa, currency, label, "funding_amount")
    elif funding_type == Budget.FundingType.FIXED_AMOUNT:
        raise CommandError(
            f"{label}: 'funding_amount' is required when "
            "funding_type is 'fixed_amount'."
        )

    # target_date (required for goal + target_date)
    #
    target_date: date | None = None
    raw_td = raw.get("target_date")
    if raw_td is not None:
        if isinstance(raw_td, date):
            target_date = raw_td
        else:
            try:
                target_date = date.fromisoformat(str(raw_td))
            except ValueError as exc:
                raise CommandError(
                    f"{label}: 'target_date' is not a valid ISO date: {raw_td!r}"
                ) from exc
    elif (
        budget_type == Budget.BudgetType.GOAL
        and funding_type == Budget.FundingType.TARGET_DATE
    ):
        raise CommandError(
            f"{label}: 'target_date' is required for a goal budget "
            "with funding_type 'target_date'."
        )

    # funding_schedule
    #
    funding_schedule_obj: Any = None
    raw_fs = raw.get("funding_schedule")
    if raw_fs:
        funding_schedule_obj = _parse_recurrence(
            str(raw_fs), label, "funding_schedule"
        )

    # recurrence_schedule (optional, only meaningful for recurring)
    #
    recurrence_schedule_obj: Any = None
    raw_rs = raw.get("recurrence_schedule")
    if raw_rs:
        recurrence_schedule_obj = _parse_recurrence(
            str(raw_rs), label, "recurrence_schedule"
        )

    entry: dict[str, Any] = {
        "id": uid,
        "name": str(name),
        "budget_type": budget_type,
        "funding_type": funding_type,
        "target_balance": target_balance,
        "with_fillup_goal": bool(raw.get("with_fillup_goal", False)),
        "paused": bool(raw.get("paused", False)),
        "_funding_schedule_obj": funding_schedule_obj,
        "_recurrence_schedule_obj": recurrence_schedule_obj,
    }
    if funding_amount is not None:
        entry["funding_amount"] = funding_amount
    if target_date is not None:
        entry["target_date"] = target_date
    memo = raw.get("memo")
    if memo:
        entry["memo"] = str(memo)

    return entry


####################################################################
#
def _check_duplicate_ids(entries: list[dict[str, Any]]) -> None:
    """Raise CommandError if any two entries share the same explicit UUID.

    Args:
        entries: Normalized entry dicts from _parse_entry().

    Raises:
        CommandError: On duplicate id values within the file.
    """
    seen: set[UUID] = set()
    for entry in entries:
        uid = entry.get("id")
        if uid is not None:
            if uid in seen:
                raise CommandError(
                    f"Duplicate id in YAML: {uid}  "
                    f"(budget name: {entry['name']!r})"
                )
            seen.add(uid)


####################################################################
#
def _budget_exists(uid: UUID | None) -> bool:
    """Return True if a Budget with this UUID exists in the DB.

    Args:
        uid: Budget UUID, or None.

    Returns:
        True if a Budget with this id exists.
    """
    if uid is None:
        return False
    return Budget.objects.filter(id=uid).exists()


####################################################################
#
def _get_budget(uid: UUID | None) -> Budget | None:
    """Return the Budget with this UUID, or None.

    Args:
        uid: Budget UUID, or None.

    Returns:
        Budget instance or None.
    """
    if uid is None:
        return None
    return Budget.objects.filter(id=uid).first()


####################################################################
#
def _normalize_type(value: str, label: str) -> str:
    """Normalize a human-readable budget type string to its model code.

    Args:
        value: Raw type string from YAML.
        label: Context label for error messages.

    Returns:
        Single-character BudgetType code.

    Raises:
        CommandError: On unrecognized value.
    """
    normalized = _BUDGET_TYPE_MAP.get(str(value).lower().strip())
    if normalized is None:
        valid = ", ".join(_BUDGET_TYPE_MAP.keys())
        raise CommandError(
            f"{label}: unknown budget type {value!r}.  Valid values: {valid}"
        )
    return normalized


####################################################################
#
def _normalize_funding_type(value: str, label: str) -> str:
    """Normalize a human-readable funding type string to its model code.

    Args:
        value: Raw funding_type string from YAML.
        label: Context label for error messages.

    Returns:
        Single-character FundingType code.

    Raises:
        CommandError: On unrecognized value.
    """
    normalized = _FUNDING_TYPE_MAP.get(str(value).lower().strip())
    if normalized is None:
        valid = ", ".join(_FUNDING_TYPE_MAP.keys())
        raise CommandError(
            f"{label}: unknown funding_type {value!r}.  Valid values: {valid}"
        )
    return normalized


####################################################################
#
def _parse_money(value: Any, currency: str, label: str, field: str) -> Money:
    """Parse a YAML money value (string or number) into a Money instance.

    Args:
        value: Raw value from YAML.
        currency: Currency code inherited from the bank account.
        label: Context label for error messages.
        field: Field name for error messages.

    Returns:
        A Money instance.

    Raises:
        CommandError: On invalid decimal value.
    """
    try:
        return Money(Decimal(str(value)), currency)
    except InvalidOperation as exc:
        raise CommandError(
            f"{label}: invalid decimal for '{field}': {value!r}"
        ) from exc


####################################################################
#
def _parse_recurrence(value: str, label: str, field: str) -> Any:
    """Parse an RFC 5545 recurrence string.

    Args:
        value: RFC 5545 string from YAML.
        label: Context label for error messages.
        field: Field name for error messages.

    Returns:
        A recurrence.Recurrence object.

    Raises:
        CommandError: On parse failure.
    """
    try:
        return recurrence.deserialize(value)
    except Exception as exc:
        raise CommandError(
            f"{label}: could not parse '{field}' as RFC 5545: {exc}"
        ) from exc


####################################################################
#
def _next_occurrences(
    sched: Any, n: int = 3, after: date | None = None
) -> list[date]:
    """Return up to n next occurrences of a recurrence schedule.

    Args:
        sched: A recurrence.Recurrence object.
        n: Maximum number of occurrences to return.
        after: Start date (defaults to today).

    Returns:
        List of upcoming occurrence dates (up to n).
    """
    from datetime import datetime

    start = after or date.today()
    start_dt = datetime(start.year, start.month, start.day)
    try:
        occurrences = list(recurrence.occurrences(sched, start_dt, inc=False))
        result = []
        for occ in occurrences:
            result.append(occ.date() if hasattr(occ, "date") else occ)
            if len(result) >= n:
                break
        return result
    except Exception:
        return []
