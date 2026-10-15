"""
Simulate bank activity for development data and timeline testing.

Acts as a fake bank.  A scenario file describes a financial life
(paychecks split across bank accounts, bills, everyday card spending,
transfers between banks, credit card statements and payments, savings
interest) and a simulated clock.  The simulator plays that life forward
and hands each simulated bank account's transactions to the same
scrape-sync service the live bank importer uses, then applies merchant
details and categories and links transfers across bank accounts, as the
importer does.

    init     write a new scenario file, names made up by Faker
    fill     create the bank accounts and simulate start..clock
    advance  move the clock on, one day at a time: sync each day's
             activity, then run budget funding for that day
    reset    delete the simulated bank accounts

Scheduled funding is switched off for the simulated bank accounts
(`auto_funding_enabled=False`); `advance` funds them itself with the
simulated date, so budgets fill on the simulated timeline whether or
not Celery is running.  The clock never passes the real today.

It does not create budgets or allocations.  Needs the database and
Redis (balance locks), not the web service.  `init` needs Faker, a dev
dependency.

Usage:

    uv run python app/manage.py simulate_bank_activity init sim.yaml \\
        --owner you@example.com --start 2026-06-01 --through 2026-08-01
    uv run python app/manage.py simulate_bank_activity fill sim.yaml
    uv run python app/manage.py simulate_bank_activity advance sim.yaml 1d
    uv run python app/manage.py simulate_bank_activity advance sim.yaml --to 15
    uv run python app/manage.py simulate_bank_activity reset sim.yaml
"""

# system imports
#
import calendar
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

# 3rd party imports
#
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import IntegrityError
from django.db.models import Q
from django.utils import timezone
from djmoney.money import Money

# Project imports
#
from moneypools.models import Bank, BankAccount, Transaction
from moneypools.service import bank_account as bank_account_svc
from moneypools.service import categories as categories_svc
from moneypools.service import funding as funding_svc
from moneypools.service import linking as linking_svc
from moneypools.service import sync_scrape as sync_scrape_svc
from moneypools.service import transaction_details as transaction_details_svc
from moneypools.service.shared import funding_system_user
from moneypools.simulator.config import (
    AccountConfig,
    ConfigError,
    Scenario,
    load_scenario,
    set_clock,
)
from moneypools.simulator.generator import (
    SimTransaction,
    as_of,
    ending_balance,
    simulate,
)
from users.models import User

_ACCOUNT_TYPES = {
    "checking": BankAccount.BankAccountType.CHECKING,
    "savings": BankAccount.BankAccountType.SAVINGS,
    "credit_card": BankAccount.BankAccountType.CREDIT_CARD,
}

# Every sync re-sends posted transactions from this far before the last
# posted date mibudge has; the rows it already has dedup away.
#
_RESEND_DAYS = 7

# 'init' starts this many days before --through unless --start says.
#
_DEFAULT_HISTORY_DAYS = 90

_STEP_RE = re.compile(r"^(\d+)([dw])$")


####################################################################
#
def _parse_date(value: str) -> date:
    """argparse type for a YYYY-MM-DD date."""
    return date.fromisoformat(value)


####################################################################
#
def advance_target(clock: date, step: str | None, to: str | None) -> date:
    """Work out the date an `advance` moves the clock to.

    Args:
        clock: The current simulated date.
        step: 'Nd' or 'Nw' -- that many days or weeks on.
        to: A day of the month (the next one after `clock`; past a short
            month's end means its last day) or a YYYY-MM-DD date.

    Returns:
        The new clock date.

    Raises:
        CommandError: If neither or both are given, or one is malformed.
    """
    if (step is None) == (to is None):
        raise CommandError("Give a step (1d, 2w) or --to, not both.")
    if step is not None:
        m = _STEP_RE.match(step)
        if not m or int(m.group(1)) < 1:
            raise CommandError(f"Step {step!r} must look like 1d or 2w.")
        days = int(m.group(1)) * (7 if m.group(2) == "w" else 1)
        return clock + timedelta(days=days)

    assert to is not None
    if to.isdigit():
        dom = int(to)
        if not 1 <= dom <= 31:
            raise CommandError(f"--to {to}: not a day of the month.")
        year, month = clock.year, clock.month
        if clock.day >= min(dom, calendar.monthrange(year, month)[1]):
            year, month = divmod(year * 12 + month, 12)
            month += 1
        return date(year, month, min(dom, calendar.monthrange(year, month)[1]))
    try:
        return date.fromisoformat(to)
    except ValueError as exc:
        raise CommandError(
            f"--to {to!r} must be a day of the month or a YYYY-MM-DD date."
        ) from exc


########################################################################
########################################################################
#
class Command(BaseCommand):
    help = (
        "Simulate bank accounts and their transactions for development "
        "data, and step a simulated clock forward."
    )

    ####################################################################
    #
    def add_arguments(self, parser: CommandParser) -> None:
        verbs = parser.add_subparsers(dest="verb", required=True)

        init = verbs.add_parser("init", help="Write a new scenario file.")
        init.add_argument("scenario", type=Path)
        init.add_argument(
            "--owner",
            required=True,
            help="Email of the existing user who owns the bank accounts.",
        )
        init.add_argument(
            "--through",
            type=_parse_date,
            metavar="YYYY-MM-DD",
            help="Initial clock (default: today).",
        )
        init.add_argument(
            "--start",
            type=_parse_date,
            metavar="YYYY-MM-DD",
            help=(
                "First simulated day (default: "
                f"{_DEFAULT_HISTORY_DAYS} days before --through)."
            ),
        )
        init.add_argument("--seed", type=int, default=1)

        fill = verbs.add_parser(
            "fill", help="Create the bank accounts and simulate to the clock."
        )
        fill.add_argument("scenario", type=Path)

        advance = verbs.add_parser(
            "advance", help="Move the clock on, syncing and funding daily."
        )
        advance.add_argument("scenario", type=Path)
        advance.add_argument("step", nargs="?", help="How far: 1d, 3d, 2w, ...")
        advance.add_argument(
            "--to", help="A day of the month (15) or a date (YYYY-MM-DD)."
        )

        reset = verbs.add_parser(
            "reset", help="Delete the simulated bank accounts."
        )
        reset.add_argument("scenario", type=Path)

    ####################################################################
    #
    def handle(self, *args: Any, **options: Any) -> None:
        path: Path = options["scenario"]
        match options["verb"]:
            case "init":
                self._init(path, options)
            case "fill":
                self._fill(path)
            case "advance":
                self._advance(path, options["step"], options["to"])
            case "reset":
                self._reset(path)

    ####################################################################
    #
    def _init(self, path: Path, options: dict[str, Any]) -> None:
        """Write a new scenario file."""
        # Faker is a dev dependency; only 'init' needs it, so the other
        # verbs run without it.
        from moneypools.simulator.scenario import render_scenario

        if path.exists():
            raise CommandError(f"{path} already exists.")
        owner = _owner(options["owner"])
        today = _today(owner)
        through: date = options["through"] or today
        start: date = options["start"] or (
            through - timedelta(days=_DEFAULT_HISTORY_DAYS)
        )
        if through > today:
            raise CommandError("--through must not be later than today.")
        if start > through:
            raise CommandError("--start must not be later than --through.")
        path.write_text(
            render_scenario(owner.email, start, through, options["seed"]),
            encoding="utf-8",
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {path} ({start} to {through}).  Next: "
                f"simulate_bank_activity fill {path}"
            )
        )

    ####################################################################
    #
    def _fill(self, path: Path) -> None:
        """Create the bank accounts and simulate start..clock."""
        scenario = _load(path)
        owner = _owner(scenario.owner_email)
        _check_not_future(scenario.clock, owner)
        banks = {name: _bank(name) for name in scenario.bank_names}
        existing = [
            a for a in scenario.accounts if _find(a, banks[a.bank], owner)
        ]
        if existing:
            raise CommandError(
                f"{existing[0].name} already exists; use 'advance', or "
                "'reset' first to start over."
            )
        accounts = {
            a.key: self._create(a, banks[a.bank], owner)
            for a in scenario.accounts
        }

        self.stdout.write(
            f"Simulating {scenario.start} through {scenario.clock}"
        )
        txns = simulate(scenario, _owner_name(owner), scenario.clock)
        run = _Run(self, scenario, owner, accounts)
        for key in accounts:
            run.sync(key, txns, scenario.clock, notify=False, verbose=True)
        run.link()

    ####################################################################
    #
    def _advance(self, path: Path, step: str | None, to: str | None) -> None:
        """Move the clock on, syncing and funding one day at a time."""
        scenario = _load(path)
        owner = _owner(scenario.owner_email)
        target = advance_target(scenario.clock, step, to)
        if target <= scenario.clock:
            raise CommandError(
                f"{target} is not after the clock ({scenario.clock})."
            )
        _check_not_future(target, owner)

        accounts: dict[str, BankAccount] = {}
        for acct in scenario.accounts:
            bank = Bank.objects.filter(name=acct.bank).first()
            found = _find(acct, bank, owner) if bank else None
            if found is None:
                raise CommandError(
                    f"{acct.name} does not exist; run 'fill' first."
                )
            accounts[acct.key] = found

        txns = simulate(scenario, _owner_name(owner), target)
        actor = funding_system_user()
        run = _Run(self, scenario, owner, accounts)
        day = scenario.clock
        while day < target:
            day += timedelta(days=1)
            today_txns = as_of(txns, day)
            for key in accounts:
                run.sync(key, today_txns, day, notify=day == target)
            transfers = sum(
                funding_svc.fund_account(account, day, actor).transfers
                for account in accounts.values()
            )
            set_clock(path, day)
            self.stdout.write(
                f"{day} {day:%a}: {run.day_posted} posted, "
                f"{run.day_pending} pending, "
                f"{transfers} funding transfer{'' if transfers == 1 else 's'}"
            )
            run.day_posted = run.day_pending = 0
        run.link()

    ####################################################################
    #
    def _reset(self, path: Path) -> None:
        """Delete the simulated bank accounts (and emptied banks)."""
        scenario = _load(path)
        owner = _owner(scenario.owner_email)
        for name in scenario.bank_names:
            bank = Bank.objects.filter(name=name).first()
            if bank is None:
                continue
            for acct in scenario.accounts:
                if acct.bank != name:
                    continue
                account = _find(acct, bank, owner)
                if account is not None:
                    bank_account_svc.delete(account)
                    self.stdout.write(f"Deleted {acct.name}")
            if not BankAccount.objects.filter(bank=bank).exists():
                bank.delete()

    ####################################################################
    #
    def _create(
        self, acct: AccountConfig, bank: Bank, owner: User
    ) -> BankAccount:
        """Create one simulated bank account, with scheduled funding off."""
        try:
            account = bank_account_svc.create(
                bank,
                acct.name,
                _ACCOUNT_TYPES[acct.type],
                owners=[owner],
                account_number=acct.account_number,
                link_aliases=list(acct.link_aliases),
                auto_funding_enabled=False,
            )
        except IntegrityError as exc:
            raise CommandError(
                f"Could not create {acct.name}: account number "
                f"{acct.account_number} is already in use."
            ) from exc
        self.stdout.write(f"Created {acct.name} ({bank.name})")
        return account


########################################################################
########################################################################
#
class _Run:
    """Syncs, enrichment and linking for one command run."""

    ####################################################################
    #
    def __init__(
        self,
        command: Command,
        scenario: Scenario,
        owner: User,
        accounts: dict[str, BankAccount],
    ) -> None:
        self.command = command
        self.scenario = scenario
        self.owner = owner
        self.accounts = accounts
        self.tz = ZoneInfo(owner.timezone)
        self.new_ids: list[str] = []
        self.categories: dict[str, Any] = {}
        self.day_posted = 0
        self.day_pending = 0

    ####################################################################
    #
    def sync(
        self,
        key: str,
        txns: list[SimTransaction],
        through: date,
        notify: bool,
        verbose: bool = False,
    ) -> None:
        """Send one bank account's snapshot on `through` to the sync."""
        account = self.accounts[key]
        account.refresh_from_db()
        resend_from = (
            account.last_posted_through - timedelta(days=_RESEND_DAYS)
            if account.last_posted_through
            else self.scenario.start
        )
        rows = sorted(
            (
                t
                for t in txns
                if t.account == key
                and (t.is_pending(through) or t.settle_date >= resend_from)
            ),
            key=lambda t: (
                t.is_pending(through),
                min(t.settle_date, through),
                t.purchase_date,
            ),
            reverse=True,
        )

        currency = account.currency
        payload = sync_scrape_svc.ScrapeSyncPayload(
            scraped_at=datetime.combine(through, time(12), tzinfo=self.tz),
            ending_balance=Money(ending_balance(txns, key, through), currency),
            transactions=[
                sync_scrape_svc.ScrapedTransaction(
                    is_pending=t.is_pending(through),
                    posted_date=datetime.combine(
                        min(t.settle_date, through), time(0), tzinfo=self.tz
                    ),
                    raw_description=t.description_at(through),
                    amount=Money(t.amount_at(through), currency),
                    transaction_type=t.transaction_type,
                )
                for t in rows
            ],
        )
        report = sync_scrape_svc.sync_scrape(account, payload, notify=notify)
        self.new_ids += report.new_transaction_ids
        self.day_posted += report.inserted_posted
        self.day_pending += report.inserted_pending

        enriched = self.enrich(report.details_needed, rows)
        out = self.command.stdout
        if verbose:
            out.write(
                f"  {account.name}: {report.inserted_posted} posted, "
                f"{report.inserted_pending} pending, {enriched} enriched"
            )
        if report.balance_mismatch is not None:
            out.write(
                self.command.style.WARNING(
                    f"  {account.name} on {through}: balance differs from "
                    f"the simulation by {report.balance_mismatch:+.2f}"
                )
            )

    ####################################################################
    #
    def enrich(
        self,
        needed: list[sync_scrape_svc.DetailsNeededRow],
        rows: list[SimTransaction],
    ) -> int:
        """Apply merchant details and categories to newly posted rows."""
        by_id = {
            str(tx.id): tx
            for tx in Transaction.objects.filter(
                id__in=[n.transaction_id for n in needed]
            )
        }
        enriched = 0
        for row in needed:
            sim = rows[row.index]
            tx = by_id.get(row.transaction_id)
            if tx is None or (sim.details is None and sim.category is None):
                continue
            status, _ = transaction_details_svc.apply_details(
                tx, sim.details or {}, category=self.category(sim.category)
            )
            enriched += status == transaction_details_svc.STATUS_APPLIED
        return enriched

    ####################################################################
    #
    def category(self, full_name: str | None) -> Any:
        """Resolve a category full name once per run, warning if unknown."""
        if not full_name:
            return None
        if full_name not in self.categories:
            found = categories_svc.find_category_for_user(self.owner, full_name)
            if found is None:
                self.command.stdout.write(
                    self.command.style.WARNING(
                        f"  unknown category {full_name!r}"
                    )
                )
            self.categories[full_name] = found
        return self.categories[full_name]

    ####################################################################
    #
    def link(self) -> None:
        """Link new transfer and card payment rows to their counterparts.

        The sync also queues a Celery link task for every new row; this
        pass links whatever those have not (or will not, with no worker
        running), so the summary counts every new row that is linked.
        """
        hints = Q(raw_description__contains="ENDING IN")
        for acct in self.scenario.accounts:
            for alias in acct.link_aliases:
                hints |= Q(raw_description__icontains=alias)
        for tx in Transaction.objects.filter(
            hints, id__in=self.new_ids, linked_transaction__isnull=True
        ):
            tx.refresh_from_db()
            if tx.linked_transaction_id is None:
                linking_svc.attempt_link(tx)
        linked = Transaction.objects.filter(
            id__in=self.new_ids, linked_transaction__isnull=False
        ).count()
        self.command.stdout.write(
            self.command.style.SUCCESS(
                f"Done; {linked} new transactions are linked to their "
                "counterparts."
            )
        )


####################################################################
#
def _load(path: Path) -> Scenario:
    """Load a scenario file, turning problems into a CommandError."""
    try:
        return load_scenario(path)
    except (ConfigError, OSError) as exc:
        raise CommandError(f"{path}: {exc}") from exc


####################################################################
#
def _owner(email: str) -> User:
    """The existing user who owns the simulated bank accounts."""
    user = User.objects.filter(email__iexact=email).first()
    if user is None:
        raise CommandError(
            f"No user has the email {email}; create the user first (for "
            "example with 'manage.py createsuperuser')."
        )
    return user


####################################################################
#
def _owner_name(owner: User) -> str:
    """How payroll and bill-pay descriptions name the owner."""
    return owner.name or owner.email.split("@")[0]


####################################################################
#
def _today(owner: User) -> date:
    """The real today in the owner's timezone."""
    return timezone.localdate(timezone=ZoneInfo(owner.timezone))


####################################################################
#
def _check_not_future(day: date, owner: User) -> None:
    """Refuse a simulated date later than the real today."""
    if day > _today(owner):
        raise CommandError(
            f"{day} is later than today; the simulated clock cannot pass "
            "the real date."
        )


####################################################################
#
def _bank(name: str) -> Bank:
    """The bank called `name`, created when missing."""
    bank = Bank.objects.filter(name=name).first()
    return bank if bank is not None else Bank.objects.create(name=name)


####################################################################
#
def _find(acct: AccountConfig, bank: Bank, owner: User) -> BankAccount | None:
    """The existing bank account for `acct`, if any.

    Raises:
        CommandError: If it exists but is not owned by `owner` -- the
            simulator never touches anyone else's bank account.
    """
    account = BankAccount.objects.filter(bank=bank, name=acct.name).first()
    if account is not None and not account.owners.filter(pk=owner.pk).exists():
        raise CommandError(
            f"Bank account {account} exists but is not owned by "
            f"{owner.email}; refusing to touch it.  Choose another bank or "
            "bank account name in the scenario."
        )
    return account
