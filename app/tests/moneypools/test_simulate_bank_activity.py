#!/usr/bin/env python
#
"""Test the bank activity simulator and its management command."""

# system imports
#
from collections.abc import Callable
from dataclasses import replace
from datetime import date, timedelta
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

# 3rd party imports
#
import pytest
import pytest_check as check
import yaml
from django.core.management import call_command
from django.core.management.base import CommandError
from djmoney.money import Money
from pytest_mock import MockerFixture

# Project imports
#
from moneypools.management.commands.simulate_bank_activity import (
    advance_target,
)
from moneypools.models import (
    Bank,
    BankAccount,
    Budget,
    InternalTransaction,
    Transaction,
)
from moneypools.service import funding as funding_svc
from moneypools.simulator.config import ConfigError, Scenario, parse_scenario
from moneypools.simulator.generator import as_of, simulate
from moneypools.simulator.holidays import (
    fed_holidays,
    next_business_day,
    previous_business_day,
)
from moneypools.simulator.scenario import render_scenario
from notifications.models import Notification
from users.models import User

pytestmark = pytest.mark.django_db

# The fill covers a cross-bank transfer (Aug 3 -> 4) and the travel card's
# e-payment from checking (Aug 28); advancing to the 16th covers the
# rewards card's payment on Tuesday Sep 15.
#
START = date(2026, 8, 1)
CLOCK = date(2026, 9, 14)


####################################################################
#
def _scenario_raw(owner: str = "owner@example.com") -> dict[str, Any]:
    """A rendered scenario as a mapping."""
    return yaml.safe_load(render_scenario(owner, START, CLOCK, seed=3))


####################################################################
#
@pytest.fixture
def scenario_path(tmp_path: Path, user: User) -> Path:
    """A scenario file owned by `user`, from START to CLOCK."""
    path = tmp_path / "sim.yaml"
    path.write_text(render_scenario(user.email, START, CLOCK, seed=3))
    return path


####################################################################
#
@pytest.fixture
def scenario(scenario_path: Path) -> Scenario:
    """The parsed `scenario_path`."""
    return parse_scenario(yaml.safe_load(scenario_path.read_text()))


####################################################################
#
@pytest.fixture
def sim(scenario_path: Path) -> Callable[..., str]:
    """Run a simulator verb against `scenario_path`; returns the output."""

    def run(verb: str, *args: str) -> str:
        out = StringIO()
        call_command(
            "simulate_bank_activity",
            verb,
            str(scenario_path),
            *args,
            stdout=out,
        )
        return out.getvalue()

    return run


####################################################################
#
@pytest.fixture
def filled(sim: Callable[..., str]) -> str:
    """The scenario filled from START to CLOCK; the fill's output."""
    return sim("fill")


####################################################################
#
@pytest.fixture
def fund_spy(mocker: MockerFixture) -> MagicMock:
    """Watch `fund_account` calls while letting them run."""
    return mocker.spy(funding_svc, "fund_account")


####################################################################
#
@pytest.fixture
def goal_on_the_15th(
    filled: str, scenario: Scenario, user: User, tmp_path: Path
) -> Budget:
    """A $50-a-month goal on the filled checking account, funding the 15th.

    Defined with `define_budgets`, the way docs/simulator.md shows.  Its
    funding schedule's DTSTART (Sep 15) is inside the simulated window;
    without one, the budget would be anchored on the real date and never
    fund on a simulated day.
    """
    checking = BankAccount.objects.get(
        owners=user, name=scenario.account("checking").name
    )
    path = tmp_path / "budgets.yaml"
    path.write_text(
        f'bank_account: "{checking.id}"\n'
        "budgets:\n"
        "  - name: Vacation\n"
        "    type: goal\n"
        "    funding_type: fixed_amount\n"
        '    target_balance: "300.00"\n'
        '    funding_amount: "50.00"\n'
        "    funding_schedule: |\n"
        "      DTSTART:20260915T000000Z\n"
        "      RRULE:FREQ=MONTHLY;BYMONTHDAY=15\n"
    )
    call_command("define_budgets", str(path), stdout=StringIO())
    return Budget.objects.get(bank_account=checking, name="Vacation")


####################################################################
#
def _sim_transactions(scenario: Scenario) -> Any:
    """Every transaction in the scenario's bank accounts."""
    return Transaction.objects.filter(
        bank_account__bank__name__in=scenario.bank_names
    )


########################################################################
########################################################################
#
class TestInit:
    """`init` writes a scenario file."""

    ####################################################################
    #
    def test_writes_a_valid_scenario(self, tmp_path: Path, user: User) -> None:
        """
        GIVEN: an existing user
        WHEN:  init writes a scenario for them
        THEN:  the file parses, names them as owner and holds the dates
        """
        path = tmp_path / "new.yaml"

        call_command(
            "simulate_bank_activity",
            "init",
            str(path),
            "--owner",
            user.email,
            "--start",
            START.isoformat(),
            "--through",
            CLOCK.isoformat(),
            stdout=StringIO(),
        )

        scenario = parse_scenario(yaml.safe_load(path.read_text()))
        check.equal(scenario.owner_email, user.email, "names the owner")
        check.equal(
            (scenario.start, scenario.clock), (START, CLOCK), "holds the dates"
        )
        check.equal(len(scenario.bank_names), 3, "spans three banks")

    ####################################################################
    #
    def test_refuses_unknown_owner(self, tmp_path: Path) -> None:
        """
        GIVEN: no user with the given email
        WHEN:  init runs
        THEN:  it refuses, writing nothing
        """
        path = tmp_path / "new.yaml"

        with pytest.raises(CommandError, match="No user"):
            call_command(
                "simulate_bank_activity",
                "init",
                str(path),
                "--owner",
                "nobody@example.com",
                stdout=StringIO(),
            )

        assert not path.exists()


########################################################################
########################################################################
#
class TestFill:
    """`fill` creates the bank accounts and their history."""

    ####################################################################
    #
    def test_builds_consistent_history(
        self, filled: str, scenario: Scenario, user: User
    ) -> None:
        """
        GIVEN: a scenario
        WHEN:  it is filled
        THEN:  its bank accounts exist with scheduled funding off, and the
               history balances, carries pending rows, categories and
               merchant details, links transfers within and across banks,
               and sends no notifications
        """
        accounts = BankAccount.objects.filter(owners=user)
        txns = _sim_transactions(scenario)
        check.equal(accounts.count(), 6, "creates the six bank accounts")
        check.is_false(
            accounts.filter(auto_funding_enabled=True).exists(),
            "turns scheduled funding off",
        )
        check.is_not_in("balance differs", filled, "matches the simulation")
        check.is_true(txns.filter(pending=True).exists(), "has pending rows")
        check.is_true(
            txns.filter(category__isnull=False).exists(), "assigns categories"
        )
        check.is_true(
            txns.filter(merchant_city__isnull=False).exists(),
            "applies merchant details",
        )
        check.is_true(
            txns.filter(
                raw_description__contains="DES:EPAY",
                linked_transaction__isnull=False,
            ).exists(),
            "links the other bank's card payment through its alias",
        )
        check.is_true(
            txns.filter(
                raw_description__startswith="EXTERNAL TRANSFER",
                linked_transaction__isnull=False,
            ).exists(),
            "links a transfer between banks",
        )
        check.is_false(Notification.objects.exists(), "sends no notifications")
        call_command("verify_balances", stdout=StringIO())

    ####################################################################
    #
    def test_refuses_to_fill_twice(
        self, filled: str, sim: Callable[..., str]
    ) -> None:
        """
        GIVEN: a filled scenario
        WHEN:  it is filled again
        THEN:  fill refuses
        """
        with pytest.raises(CommandError, match="already exists"):
            sim("fill")

    ####################################################################
    #
    def test_refuses_bank_account_of_another_user(
        self,
        scenario: Scenario,
        sim: Callable[..., str],
        bank_factory: Callable[..., Bank],
        bank_account_factory: Callable[..., BankAccount],
        user_factory: Callable[..., User],
    ) -> None:
        """
        GIVEN: a bank account with a scenario's name, owned by someone else
        WHEN:  the scenario is filled
        THEN:  fill refuses, leaving that bank account untouched
        """
        first = scenario.accounts[0]
        account = bank_account_factory(
            bank=bank_factory(name=first.bank),
            name=first.name,
            owners=[user_factory()],
        )

        with pytest.raises(CommandError, match="not owned by"):
            sim("fill")

        assert not Transaction.objects.filter(bank_account=account).exists()


########################################################################
########################################################################
#
class TestAdvance:
    """`advance` moves the clock, syncing and funding day by day."""

    ####################################################################
    #
    def test_steps_each_day_and_funds_it(
        self,
        filled: str,
        sim: Callable[..., str],
        scenario: Scenario,
        scenario_path: Path,
        fund_spy: MagicMock,
    ) -> None:
        """
        GIVEN: a filled scenario with pending purchases
        WHEN:  it advances to the 16th
        THEN:  each day is funded with its own date, the clock line moves
               and the rest of the file is kept, pending purchases post,
               the same-bank card payment is linked, notifications come
               from the last day, and the balances still verify
        """
        pending = set(
            _sim_transactions(scenario)
            .filter(pending=True)
            .values_list("bank_account", "transaction_date")
        )
        assert pending

        output = sim("advance", "--to", "16")

        days = sorted({c.args[1] for c in fund_spy.call_args_list})
        posted = set(
            _sim_transactions(scenario)
            .filter(pending=False)
            .values_list("bank_account", "transaction_date")
        )
        text = scenario_path.read_text()
        check.equal(
            days, [date(2026, 9, 15), date(2026, 9, 16)], "funds each day"
        )
        check.equal(len(fund_spy.call_args_list), 12, "every bank account")
        check.is_in("clock: 2026-09-16\n", text, "moves the clock")
        check.is_in("# The simulated", text, "keeps the file's comments")
        check.is_true(pending <= posted, "earlier pending rows are posted")
        check.is_true(
            _sim_transactions(scenario)
            .filter(
                raw_description__contains="CREDIT CARD DES:PAYMENT",
                linked_transaction__isnull=False,
            )
            .exists(),
            "links the same-bank card payment",
        )
        check.is_true(Notification.objects.exists(), "notifies at the end")
        check.is_not_in("balance differs", output, "matches the simulation")
        call_command("verify_balances", stdout=StringIO())

    ####################################################################
    #
    def test_funds_a_budget_on_its_simulated_day(
        self, goal_on_the_15th: Budget, sim: Callable[..., str]
    ) -> None:
        """
        GIVEN: a filled scenario with a goal funding on the 15th
        WHEN:  the clock advances past the 15th
        THEN:  the goal is funded on the simulated 15th
        """
        sim("advance", "--to", "16")

        goal_on_the_15th.refresh_from_db()
        check.is_true(
            InternalTransaction.objects.filter(
                dst_budget=goal_on_the_15th,
                system_event_date=date(2026, 9, 15),
            ).exists(),
            "funds it on the simulated date",
        )
        check.equal(goal_on_the_15th.balance, Money(50, "USD"), "with $50")

    ####################################################################
    #
    def test_refuses_to_pass_today(
        self, filled: str, sim: Callable[..., str], scenario_path: Path
    ) -> None:
        """
        GIVEN: a filled scenario
        WHEN:  it is advanced past the real today
        THEN:  advance refuses and the clock stays put
        """
        with pytest.raises(CommandError, match="later than today"):
            sim("advance", "--to", "2099-01-01")

        assert f"clock: {CLOCK}\n" in scenario_path.read_text()

    ####################################################################
    #
    def test_refuses_before_fill(self, sim: Callable[..., str]) -> None:
        """
        GIVEN: a scenario that was never filled
        WHEN:  it is advanced
        THEN:  advance refuses
        """
        with pytest.raises(CommandError, match="run 'fill' first"):
            sim("advance", "1d")

    ####################################################################
    #
    @pytest.mark.parametrize(
        "step,to,expected",
        [
            ("1d", None, date(2026, 9, 15)),
            ("2w", None, date(2026, 9, 28)),
            (None, "15", date(2026, 9, 15)),
            # The 14th has passed this month, so the next one.
            (None, "14", date(2026, 10, 14)),
            # Past September's end means its last day.
            (None, "31", date(2026, 9, 30)),
            (None, "2026-10-01", date(2026, 10, 1)),
        ],
    )
    def test_target(
        self, step: str | None, to: str | None, expected: date
    ) -> None:
        """
        GIVEN: the clock on 2026-09-14
        WHEN:  an advance names a step or a --to
        THEN:  it targets the expected date
        """
        assert advance_target(CLOCK, step, to) == expected

    ####################################################################
    #
    @pytest.mark.parametrize(
        "step,to",
        [
            (None, None),
            ("1d", "15"),
            ("3x", None),
            (None, "32"),
            (None, "soon"),
        ],
    )
    def test_target_rejects(self, step: str | None, to: str | None) -> None:
        """
        GIVEN: a malformed or ambiguous advance
        WHEN:  its target is worked out
        THEN:  it is refused
        """
        with pytest.raises(CommandError):
            advance_target(CLOCK, step, to)


########################################################################
########################################################################
#
class TestReset:
    """`reset` deletes the simulated bank accounts."""

    ####################################################################
    #
    def test_reset_then_fill_replays_history(
        self, filled: str, sim: Callable[..., str], scenario: Scenario
    ) -> None:
        """
        GIVEN: a filled scenario
        WHEN:  it is reset and filled again
        THEN:  the emptied banks are removed and the bank accounts come
               back with the same history
        """
        old_ids = set(BankAccount.objects.values_list("id", flat=True))
        before = set(
            _sim_transactions(scenario).values_list("raw_description", "amount")
        )

        sim("reset")
        banks_left = Bank.objects.filter(name__in=scenario.bank_names).count()
        sim("fill")

        new_ids = set(BankAccount.objects.values_list("id", flat=True))
        check.equal(banks_left, 0, "removes the emptied banks")
        check.is_false(old_ids & new_ids, "recreates the bank accounts")
        check.equal(
            set(
                _sim_transactions(scenario).values_list(
                    "raw_description", "amount"
                )
            ),
            before,
            "replays the same history",
        )


########################################################################
########################################################################
#
class TestGenerator:
    """The generator's schedules, holidays and determinism."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "schedule,month,expected",
        [
            # Both paydays are weekdays.
            ({}, date(2026, 9, 1), [date(2026, 9, 15), date(2026, 9, 30)]),
            # The 15th is a Saturday.
            ({}, date(2026, 8, 1), [date(2026, 8, 14), date(2026, 8, 31)]),
            # The 31st is a Saturday.
            ({}, date(2026, 10, 1), [date(2026, 10, 15), date(2026, 10, 30)]),
            # The 31st is Memorial Day.
            ({}, date(2027, 5, 1), [date(2027, 5, 14), date(2027, 5, 28)]),
            # Every other Friday; Christmas is one of them.
            (
                {"schedule": "biweekly", "anchor": date(2026, 12, 11)},
                date(2026, 12, 1),
                [date(2026, 12, 11), date(2026, 12, 24)],
            ),
        ],
    )
    def test_paydays_move_back_from_non_business_days(
        self, schedule: dict[str, Any], month: date, expected: list[date]
    ) -> None:
        """
        GIVEN: a semimonthly or biweekly paycheck
        WHEN:  a month is simulated
        THEN:  pay arrives on schedule, or the business day before when
               that is a weekend or holiday
        """
        raw = _scenario_raw()
        raw["paychecks"][0].update(schedule)
        scenario = replace(parse_scenario(raw), start=month)
        txns = simulate(scenario, "Jordan Example", month + timedelta(days=35))

        paydays = sorted(
            {
                t.purchase_date
                for t in txns
                if "PAYROLL" in t.posted_description
                and t.purchase_date.month == month.month
            }
        )
        assert paydays == expected

    ####################################################################
    #
    @pytest.mark.parametrize(
        "day,forward,back",
        [
            # Labor Day.
            (date(2026, 9, 7), date(2026, 9, 8), date(2026, 9, 4)),
            # Juneteenth 2027 is a Saturday: not observed on the Friday.
            (date(2027, 6, 18), date(2027, 6, 18), date(2027, 6, 18)),
            # Independence Day 2027 is a Sunday: observed the Monday.
            (date(2027, 7, 5), date(2027, 7, 6), date(2027, 7, 2)),
            # Thanksgiving.
            (date(2026, 11, 26), date(2026, 11, 27), date(2026, 11, 25)),
        ],
    )
    def test_business_days_skip_fed_holidays(
        self, day: date, forward: date, back: date
    ) -> None:
        """
        GIVEN: a date
        WHEN:  it is rolled to a business day
        THEN:  weekends and observed Federal Reserve holidays are skipped
        """
        check.equal(next_business_day(day), forward, "rolls forward")
        check.equal(previous_business_day(day), back, "rolls back")

    ####################################################################
    #
    def test_saturday_holidays_are_not_observed(self) -> None:
        """
        GIVEN: 2026, when Independence Day falls on a Saturday
        WHEN:  its Federal Reserve holidays are listed
        THEN:  there are ten, not eleven
        """
        assert len(fed_holidays(2026)) == 10

    ####################################################################
    #
    def test_identical_purchases_stay_distinct(self) -> None:
        """
        GIVEN: spending that buys the same thing at the same place many
               times a day
        WHEN:  a day is simulated
        THEN:  no two posted rows share a date, amount and description,
               so the import's dedup keeps them all
        """
        raw = _scenario_raw()
        raw["spending"] = [
            {
                "name": "vending",
                "per_week": 70,
                "amount": "2.00",
                "accounts": {"card": 1},
                "merchants": [{"name": "SNACK MACHINE"}],
            }
        ]
        scenario = replace(parse_scenario(raw), start=CLOCK)

        txns = [
            t
            for t in simulate(scenario, "Jordan Example", CLOCK)
            if t.posted_description.startswith("SNACK")
        ]

        assert len(txns) > 1
        keys = {(t.purchase_date, t.posted_amount) for t in txns}
        assert len(keys) == len(txns)

    ####################################################################
    #
    def test_history_is_stable_as_time_advances(self) -> None:
        """
        GIVEN: a scenario
        WHEN:  it is simulated through two different dates
        THEN:  the later run, cut at the earlier date, equals the earlier
               run
        """
        scenario = parse_scenario(_scenario_raw())
        early = simulate(scenario, "Jordan Example", CLOCK)
        late = simulate(scenario, "Jordan Example", date(2026, 10, 31))

        assert as_of(late, CLOCK) == early


########################################################################
########################################################################
#
class TestScenarioValidation:
    """A bad scenario fails with a message naming the problem."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "change,message",
        [
            ({"banks": []}, "at least one bank account"),
            ({"clock": date(2026, 7, 1)}, "clock is before start"),
            (
                {
                    "transfers": [
                        {
                            "from": "checking",
                            "to": "nowhere",
                            "amount": "1",
                            "day": 1,
                        }
                    ]
                },
                "unknown bank account 'nowhere'",
            ),
            (
                {
                    "spending": [
                        {
                            "name": "x",
                            "per_week": 1,
                            "amount": "5",
                            "accounts": {"card": 1},
                            "weekdays": {"someday": 1},
                            "merchants": [{"name": "M"}],
                        }
                    ]
                },
                "unknown day",
            ),
            (
                {
                    "paychecks": [
                        {
                            "employer": "E",
                            "net_amount": "100",
                            "deposits": [
                                {"account": "checking", "amount": "100"}
                            ],
                        }
                    ]
                },
                "remainder",
            ),
        ],
    )
    def test_invalid_scenario_names_the_problem(
        self, change: dict[str, Any], message: str
    ) -> None:
        """
        GIVEN: a scenario with one invalid section
        WHEN:  it is parsed
        THEN:  a ConfigError names the problem
        """
        with pytest.raises(ConfigError, match=message):
            parse_scenario({**_scenario_raw(), **change})
