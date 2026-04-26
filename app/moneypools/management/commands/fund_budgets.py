"""
Run the budget funding engine for one or all bank accounts.

Collects due funding and recurrence events (since the last run), applies
the import-freshness gate, and transfers money between budgets via
InternalTransactions.  Safe to re-run; already-processed events are
skipped via the last_funded_on / last_recurrence_on pointers.

Usage:

    uv run python app/manage.py fund_budgets
    uv run python app/manage.py fund_budgets --account <uuid-or-name>
    uv run python app/manage.py fund_budgets --date 2026-03-01
    uv run python app/manage.py fund_budgets --dry-run
"""

# system imports
#
from datetime import date
from typing import Any
from uuid import UUID

# 3rd party imports
#
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

# Project imports
#
from moneypools.models import BankAccount, Budget
from moneypools.service import funding as funding_svc


########################################################################
########################################################################
#
class Command(BaseCommand):
    help = (
        "Process due budget funding and recurrence events for all accounts "
        "(or a specific account).  Idempotent: re-running is safe."
    )

    ####################################################################
    #
    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--account",
            metavar="PATTERN",
            default=None,
            help=(
                "Restrict to the BankAccount matching this partial name "
                "or UUID prefix (same matching logic as export_bank_account)."
            ),
        )
        parser.add_argument(
            "--date",
            metavar="YYYY-MM-DD",
            default=None,
            help=(
                "Override 'today' for back-fill or testing.  "
                "Defaults to the current UTC date."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Show what would be funded without making any changes.",
        )

    ####################################################################
    #
    def handle(self, *args: Any, **options: Any) -> None:
        today = (
            _parse_date(options["date"])
            if options["date"]
            else timezone.localdate()
        )
        dry_run: bool = options["dry_run"]
        pattern: str | None = options["account"]

        if dry_run:
            self.stdout.write(
                self.style.WARNING("Dry run -- no changes will be made.")
            )

        if pattern:
            accounts = [_resolve_account(pattern)]
        else:
            accounts = list(
                BankAccount.objects.select_related(
                    "bank", "unallocated_budget"
                ).all()
            )

        if not accounts:
            self.stdout.write("No accounts found.")
            return

        actor = funding_svc.funding_system_user()

        total_transfers = 0
        total_deferred = 0
        total_warnings = 0

        for account in accounts:
            if dry_run:
                report = _dry_run_report(account, today)
            else:
                report = funding_svc.fund_account(account, today, actor)

            if report.deferred:
                total_deferred += 1
                self.stdout.write(
                    f"  DEFERRED  {account.name}  "
                    f"(last_posted_through={account.last_posted_through})"
                )
                continue

            total_transfers += report.transfers
            total_warnings += len(report.warnings)

            status = (
                self.style.SUCCESS(f"  OK        {account.name}")
                if not report.warnings
                else self.style.WARNING(f"  WARN      {account.name}")
            )
            self.stdout.write(f"{status}  {report.transfers} transfer(s)")

            for warning in report.warnings:
                self.stdout.write(f"    WARNING: {warning}")

            if report.skipped_budgets:
                self.stdout.write(
                    f"    Skipped (paused): {', '.join(report.skipped_budgets)}"
                )

        self.stdout.write("")
        self.stdout.write(
            f"Done -- {total_transfers} transfer(s), "
            f"{total_deferred} account(s) deferred, "
            f"{total_warnings} warning(s)."
        )


########################################################################
########################################################################
#
def _resolve_account(pattern: str) -> BankAccount:
    """Find a unique BankAccount by partial name or UUID fragment.

    Args:
        pattern: Full UUID, UUID prefix, or name substring.

    Returns:
        The matching BankAccount.

    Raises:
        CommandError: When zero or more than one account matches.
    """
    qs = BankAccount.objects.select_related("bank", "unallocated_budget")

    try:
        uid = UUID(pattern)
        exact = list(qs.filter(id=uid))
        if len(exact) == 1:
            return exact[0]
    except ValueError:
        pass

    matches = list(qs.filter(name__icontains=pattern))
    if not matches:
        matches = [a for a in qs.all() if pattern.lower() in str(a.id).lower()]

    if not matches:
        raise CommandError(f"No bank account matches {pattern!r}.")
    if len(matches) > 1:
        listing = "\n".join(f"  {a.name}  ({a.id})" for a in matches)
        raise CommandError(
            f"Multiple accounts match {pattern!r}:\n{listing}\n"
            "Provide a more specific pattern."
        )
    return matches[0]


####################################################################
#
def _parse_date(value: str) -> date:
    """Parse a YYYY-MM-DD date string.

    Args:
        value: Date string in YYYY-MM-DD format.

    Returns:
        A datetime.date object.

    Raises:
        CommandError: If the string is not a valid date.
    """
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CommandError(
            f"Invalid date {value!r}: expected YYYY-MM-DD."
        ) from exc


####################################################################
#
def _dry_run_report(
    account: BankAccount, today: date
) -> funding_svc.FundingReport:
    """Return a FundingReport describing what would be funded without
    making any changes.

    Args:
        account: The BankAccount to inspect.
        today: The reference date.

    Returns:
        A FundingReport with transfers=0 but deferred/warnings populated.
    """
    report = funding_svc.FundingReport(account_id=str(account.id))

    budgets = list(
        Budget.objects.filter(
            bank_account=account, archived=False
        ).select_related("fillup_goal")
    )
    events = funding_svc._collect_events(budgets, today)
    if not events:
        return report

    gate_date = max(ev.date for ev in events)
    if (
        account.last_posted_through is None
        or account.last_posted_through < gate_date
    ):
        report.deferred = True
        return report

    for ev in events:
        if ev.budget.paused:
            report.skipped_budgets.append(ev.budget.name)
        else:
            report.transfers += 1  # would-be transfer count

    return report
