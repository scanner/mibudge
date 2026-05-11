"""
Extract budget definitions to a YAML file consumable by define_budgets.

Two source modes:

  From a JSON export produced by export_bank_account:

      uv run python app/manage.py extract_budgets --from-json backup.json
      uv run python app/manage.py extract_budgets --from-json backup.json \\
          --budget "Groceries" --output groceries.yaml

  From the live database by bank account pattern:

      uv run python app/manage.py extract_budgets "Scanner's Checking"
      uv run python app/manage.py extract_budgets "Scanner's Checking" \\
          --budget "Groceries" --output groceries.yaml

Output defaults to stdout.  Use --output to write to a file.

By default archived budgets are omitted.  Pass --include-archived to
include them.  Associated fill-up goal budgets (type 'A') and the
account's unallocated budget are always omitted -- they are auto-created
by define_budgets when the parent recurring budget sets with_fillup_goal.

The emitted YAML is a valid input for define_budgets:

    extract_budgets ACCOUNT --output budgets.yaml
    define_budgets budgets.yaml --dry-run   # should show all UPDATEs
"""

# system imports
#
import json
import sys
from typing import Any

# 3rd party imports
#
import recurrence
import yaml
from django.core.management.base import BaseCommand, CommandError

# Project imports
#
from moneypools.models import Budget

from ._budget_admin import resolve_account, resolve_budget

########################################################################
########################################################################
#
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
        "Export budget definitions to YAML for use with define_budgets.  "
        "Reads from an export_bank_account JSON file or the live database."
    )

    ####################################################################
    #
    def add_arguments(self, parser: Any) -> None:
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--from-json",
            metavar="FILE",
            dest="json_file",
            help="Path to a JSON export produced by export_bank_account.",
        )
        group.add_argument(
            "account",
            nargs="?",
            metavar="ACCOUNT",
            help="Bank account name fragment or UUID (live DB lookup).",
        )
        parser.add_argument(
            "--budget",
            metavar="PATTERN",
            dest="budget_pattern",
            help=(
                "Name fragment or UUID to extract a single budget.  "
                "Omit to extract all non-archived budgets."
            ),
        )
        parser.add_argument(
            "--output",
            "-o",
            metavar="FILE",
            dest="output_file",
            help="Write YAML to this file instead of stdout.",
        )
        parser.add_argument(
            "--include-archived",
            action="store_true",
            default=False,
            dest="include_archived",
            help="Include archived budgets in the output.",
        )

    ####################################################################
    #
    def handle(self, *args: Any, **options: Any) -> None:
        json_file: str | None = options.get("json_file")
        account_pattern: str | None = options.get("account")
        budget_pattern: str | None = options.get("budget_pattern")
        output_file: str | None = options.get("output_file")
        include_archived: bool = options["include_archived"]

        if json_file:
            doc = self._from_json(json_file, budget_pattern, include_archived)
        else:
            if not account_pattern:
                raise CommandError(
                    "Provide an account name/UUID or --from-json FILE."
                )
            doc = self._from_db(
                account_pattern, budget_pattern, include_archived
            )

        account_id = doc.pop("_account_id", None)

        # Use literal block style (|) for strings containing newlines so that
        # multi-line RFC 5545 values (DTSTART + RRULE) are human-readable and
        # survive hand-editing, rather than being folded into opaque flow scalars.
        class _Dumper(yaml.Dumper):
            pass

        def _str_representer(dumper: yaml.Dumper, data: str) -> yaml.ScalarNode:
            style = "|" if "\n" in data else None
            return dumper.represent_scalar(
                "tag:yaml.org,2002:str", data, style=style
            )

        _Dumper.add_representer(str, _str_representer)

        yaml_text = yaml.dump(
            doc,
            Dumper=_Dumper,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )

        # Prepend a header comment with the source account UUID so the
        # file is self-documenting without polluting the data keys.
        #
        header_lines = ["# Generated by extract_budgets\n"]
        if account_id:
            header_lines.append(f"# bank_account_id: {account_id}\n")
        header_lines.append("#\n")
        output = "".join(header_lines) + yaml_text

        if output_file:
            with open(output_file, "w") as fh:
                fh.write(output)
            self.stderr.write(self.style.SUCCESS(f"Wrote {output_file}"))
        else:
            sys.stdout.write(output)

    ####################################################################
    #
    def _from_json(
        self,
        path: str,
        budget_pattern: str | None,
        include_archived: bool,
    ) -> dict[str, Any]:
        """Build the YAML doc from an export_bank_account JSON file.

        Args:
            path: Path to the JSON export file.
            budget_pattern: Optional name/UUID filter.
            include_archived: Whether to include archived budgets.

        Returns:
            Dict ready for yaml.dump().
        """
        with open(path) as fh:
            data: dict[str, Any] = json.load(fh)

        version = data.get("version")
        if version != 1:
            raise CommandError(
                f"Unsupported export version: {version!r}. "
                "Only version 1 is supported."
            )

        account_data = data["bank_account"]
        account_name = account_data["name"]
        account_id = account_data["id"]
        unalloc_id = account_data.get("unallocated_budget_id")

        raw_budgets: list[dict[str, Any]] = data.get("budgets", [])
        budget_entries = _filter_and_convert_json_budgets(
            raw_budgets,
            unalloc_id=unalloc_id,
            budget_pattern=budget_pattern,
            include_archived=include_archived,
        )

        return {
            "bank_account": account_name,
            "_account_id": account_id,
            "budgets": budget_entries,
        }

    ####################################################################
    #
    def _from_db(
        self,
        account_pattern: str,
        budget_pattern: str | None,
        include_archived: bool,
    ) -> dict[str, Any]:
        """Build the YAML doc from the live database.

        Args:
            account_pattern: Name fragment or UUID for the bank account.
            budget_pattern: Optional name/UUID filter for a single budget.
            include_archived: Whether to include archived budgets.

        Returns:
            Dict ready for yaml.dump().
        """
        account = resolve_account(account_pattern)

        if budget_pattern:
            budget = resolve_budget(budget_pattern, account=account)
            budgets = [budget]
        else:
            qs = Budget.objects.filter(bank_account=account).exclude(
                budget_type=Budget.BudgetType.ASSOCIATED_FILLUP_GOAL
            )
            if account.unallocated_budget_id:
                qs = qs.exclude(id=account.unallocated_budget_id)
            if not include_archived:
                qs = qs.filter(archived=False)
            budgets = list(qs.order_by("name"))

        budget_entries = [_budget_to_yaml_entry(b) for b in budgets]

        return {
            "bank_account": account.name,
            "_account_id": str(account.id),
            "budgets": budget_entries,
        }


########################################################################
########################################################################
#
def _filter_and_convert_json_budgets(
    raw_budgets: list[dict[str, Any]],
    unalloc_id: str | None,
    budget_pattern: str | None,
    include_archived: bool,
) -> list[dict[str, Any]]:
    """Filter and convert raw JSON budget dicts to YAML-ready entries.

    Args:
        raw_budgets: Budget dicts from the JSON export.
        unalloc_id: UUID string of the unallocated budget to skip.
        budget_pattern: Optional name/UUID filter.
        include_archived: Whether to include archived budgets.

    Returns:
        List of YAML-ready budget dicts.

    Raises:
        CommandError: If budget_pattern matches zero budgets.
    """
    results = []
    pattern_lower = budget_pattern.lower() if budget_pattern else None

    for bd in raw_budgets:
        # Skip auto-managed budgets.
        #
        if bd.get("budget_type") == Budget.BudgetType.ASSOCIATED_FILLUP_GOAL:
            continue
        if unalloc_id and bd.get("id") == unalloc_id:
            continue
        if not include_archived and bd.get("archived", False):
            continue

        # Apply pattern filter if given.
        #
        if pattern_lower:
            name_match = pattern_lower in bd.get("name", "").lower()
            id_match = pattern_lower in bd.get("id", "").lower()
            if not name_match and not id_match:
                continue

        results.append(_json_budget_to_yaml_entry(bd))

    if budget_pattern and not results:
        raise CommandError(
            f"No budget matching {budget_pattern!r} found in the export."
        )

    return results


####################################################################
#
def _json_budget_to_yaml_entry(bd: dict[str, Any]) -> dict[str, Any]:
    """Convert a JSON export budget dict to a define_budgets YAML entry.

    Args:
        bd: Budget dict from the JSON export (as produced by _serialize_budget).

    Returns:
        YAML-ready dict with human-readable field names.
    """
    budget_type_code = bd.get("budget_type", Budget.BudgetType.GOAL)
    funding_type_code = bd.get("funding_type", Budget.FundingType.TARGET_DATE)

    entry: dict[str, Any] = {
        "id": bd["id"],
        "name": bd["name"],
        "type": _BUDGET_TYPE_LABELS.get(budget_type_code, budget_type_code),
        "funding_type": _FUNDING_TYPE_LABELS.get(
            funding_type_code, funding_type_code
        ),
        "target_balance": _money_str(bd.get("target_balance")),
    }

    _add_optional_fields_json(entry, bd)
    return entry


####################################################################
#
def _budget_to_yaml_entry(budget: Budget) -> dict[str, Any]:
    """Convert a live Budget model instance to a define_budgets YAML entry.

    Args:
        budget: Budget ORM instance.

    Returns:
        YAML-ready dict with human-readable field names.
    """
    entry: dict[str, Any] = {
        "id": str(budget.id),
        "name": budget.name,
        "type": _BUDGET_TYPE_LABELS.get(budget.budget_type, budget.budget_type),
        "funding_type": _FUNDING_TYPE_LABELS.get(
            budget.funding_type, budget.funding_type
        ),
        "target_balance": str(budget.target_balance.amount),
    }

    _add_optional_fields_db(entry, budget)
    return entry


def _add_optional_fields_json(
    entry: dict[str, Any], bd: dict[str, Any]
) -> None:
    """Add optional fields from a JSON export budget dict.

    Args:
        entry: The output dict being built.
        bd: JSON export budget dict.
    """
    fa = bd.get("funding_amount")
    if fa and _money_str(fa) != "0.00":
        entry["funding_amount"] = _money_str(fa)

    if bd.get("target_date"):
        entry["target_date"] = bd["target_date"]

    if bd.get("with_fillup_goal"):
        entry["with_fillup_goal"] = True

    if bd.get("paused"):
        entry["paused"] = True

    fs = bd.get("funding_schedule")
    if fs:
        entry["funding_schedule"] = fs

    rs = bd.get("recurrence_schedule")
    if rs:
        entry["recurrence_schedule"] = rs

    if bd.get("memo"):
        entry["memo"] = bd["memo"]


def _add_optional_fields_db(entry: dict[str, Any], budget: Budget) -> None:
    """Add optional fields from a live Budget model instance.

    Args:
        entry: The output dict being built.
        budget: Budget ORM instance.
    """
    if budget.funding_amount is not None and budget.funding_amount.amount != 0:
        entry["funding_amount"] = str(budget.funding_amount.amount)

    if budget.target_date:
        entry["target_date"] = budget.target_date.isoformat()

    if budget.paused:
        entry["paused"] = True

    fs_str = _serialize_recurrence(budget.funding_schedule)
    if fs_str:
        entry["funding_schedule"] = fs_str

    rs_str = _serialize_recurrence(budget.recurrence_schedule)
    if rs_str:
        entry["recurrence_schedule"] = rs_str

    if budget.memo:
        entry["memo"] = budget.memo


########################################################################
########################################################################
#
def _money_str(d: dict[str, str] | None) -> str:
    """Extract the amount string from a JSON export money dict.

    Args:
        d: Dict with 'amount' and 'currency' keys, or None.

    Returns:
        Decimal string (e.g. '400.00'), or '0.00' if absent.
    """
    if d is None:
        return "0.00"
    return str(d.get("amount", "0.00"))


####################################################################
#
def _serialize_recurrence(sched: Any) -> str | None:
    """Serialize a recurrence object to its RFC 5545 string, or None.

    Args:
        sched: A recurrence.Recurrence instance, or None.

    Returns:
        RFC 5545 string, or None if empty/absent.
    """
    if not sched:
        return None
    try:
        text = recurrence.serialize(sched)
        return text if text.strip() else None
    except Exception:
        return None
