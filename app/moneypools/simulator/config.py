"""
Scenario files for the bank activity simulator.

A scenario file (YAML; `scenario_template.yaml` documents the format)
describes a simulated financial life: banks and bank accounts,
paychecks, bills, transfers and everyday spending, plus the simulated
`clock`.  `load_scenario` turns it into frozen dataclasses, validating
every field so a bad edit fails with a message naming the field rather
than as a traceback halfway through a simulation.

The `clock` line is the only part of the file the simulator writes;
`set_clock` rewrites that one line in place so the rest of the file,
comments included, is left as the user wrote it.
"""

# system imports
#
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

# 3rd party imports
#
import yaml

ACCOUNT_TYPES = ("checking", "savings", "credit_card")
SPENDING_KINDS = ("purchase", "atm", "zelle")
BILL_METHODS = ("ach", "card")
PAYCHECK_SCHEDULES = ("semimonthly", "biweekly")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# A pending card purchase must post within the window
# `description_utils.parse_transaction_date` accepts for the MM/DD
# embedded in its description (7 days); rolling past a weekend and a
# holiday adds up to three more days on top of the settle delay.
#
MAX_SETTLE_DAYS = 4

# A transfer between banks arrives up to this many days after it left.
#
MAX_LAG_DAYS = 5

# Spending without 'weekdays' is a little busier at the weekend.
#
DEFAULT_WEEKDAY_WEIGHTS = (1.0, 1.0, 1.0, 1.0, 1.0, 1.5, 1.5)

_CLOCK_RE = re.compile(r"^clock:[^\n]*$", re.MULTILINE)


########################################################################
########################################################################
#
class ConfigError(ValueError):
    """The scenario file is invalid."""


########################################################################
########################################################################
#
@dataclass(frozen=True)
class AmountSpec:
    """A fixed amount, or a range a value is drawn from."""

    low: Decimal
    high: Decimal

    @property
    def fixed(self) -> bool:
        """True when the amount is a single value, not a range."""
        return self.low == self.high


########################################################################
########################################################################
#
@dataclass(frozen=True)
class AccountConfig:
    """One simulated bank account."""

    key: str
    bank: str
    name: str
    type: str
    account_number: str
    opening_balance: Decimal = Decimal("0")
    interest_apy: Decimal | None = None
    link_aliases: tuple[str, ...] = ()
    statement_day: int | None = None
    payment_day: int | None = None
    pay_from: str | None = None

    @property
    def last4(self) -> str:
        """The last four digits of the account number."""
        return self.account_number[-4:]


########################################################################
########################################################################
#
@dataclass(frozen=True)
class DepositConfig:
    """One slice of a split paycheck."""

    account: str
    amount: Decimal | None = None
    remainder: bool = False


########################################################################
########################################################################
#
@dataclass(frozen=True)
class PaycheckConfig:
    """A recurring paycheck, possibly split across bank accounts."""

    employer: str
    schedule: str
    net_amount: Decimal
    deposits: tuple[DepositConfig, ...]
    anchor: date | None = None


########################################################################
########################################################################
#
@dataclass(frozen=True)
class TransferConfig:
    """A monthly move between two of the simulated bank accounts."""

    from_account: str
    to_account: str
    amount: AmountSpec
    day: int
    lag_days: tuple[int, int] = (0, 0)


########################################################################
########################################################################
#
@dataclass(frozen=True)
class MerchantConfig:
    """A place money is spent (or, for Zelle, a person)."""

    name: str
    city: str | None = None
    state: str | None = None
    mcc: str | None = None


########################################################################
########################################################################
#
@dataclass(frozen=True)
class BillConfig:
    """A monthly bill."""

    payee: str
    amount: AmountSpec
    day: int
    account: str
    method: str
    category: str | None = None
    merchant: MerchantConfig | None = None


########################################################################
########################################################################
#
@dataclass(frozen=True)
class SpendingConfig:
    """A kind of everyday spending."""

    name: str
    kind: str
    per_week: float
    amount: AmountSpec
    accounts: tuple[tuple[str, int], ...]
    merchants: tuple[MerchantConfig, ...]
    weekdays: tuple[float, ...] = DEFAULT_WEEKDAY_WEIGHTS
    category: str | None = None
    settle_days: tuple[int, int] = (1, 3)
    tip: tuple[float, float] | None = None
    refund_rate: float = 0.0
    round_to: Decimal | None = None


########################################################################
########################################################################
#
@dataclass(frozen=True)
class Scenario:
    """A whole scenario file."""

    seed: int
    owner_email: str
    start: date
    clock: date
    accounts: tuple[AccountConfig, ...]
    paychecks: tuple[PaycheckConfig, ...] = ()
    transfers: tuple[TransferConfig, ...] = ()
    bills: tuple[BillConfig, ...] = ()
    spending: tuple[SpendingConfig, ...] = ()

    ####################################################################
    #
    def account(self, key: str) -> AccountConfig:
        """Return the bank account configured under `key`."""
        for acct in self.accounts:
            if acct.key == key:
                return acct
        raise KeyError(key)

    ####################################################################
    #
    @property
    def bank_names(self) -> tuple[str, ...]:
        """The simulated banks, in file order."""
        return tuple(dict.fromkeys(a.bank for a in self.accounts))


####################################################################
#
def load_scenario(path: Path) -> Scenario:
    """Load and validate a scenario file.

    Args:
        path: The YAML file to read.

    Returns:
        The validated scenario.

    Raises:
        ConfigError: If the file is not valid YAML or fails validation.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("The scenario must be a mapping.")
    return parse_scenario(raw)


####################################################################
#
def set_clock(path: Path, clock: date) -> None:
    """Rewrite the scenario file's `clock:` line in place.

    Args:
        path: The scenario file.
        clock: The new simulated date.

    Raises:
        ConfigError: If the file has no top-level `clock:` line.
    """
    text = path.read_text(encoding="utf-8")
    new, count = _CLOCK_RE.subn(f"clock: {clock.isoformat()}", text, count=1)
    if count != 1:
        raise ConfigError(f"{path} has no top-level 'clock:' line.")
    path.write_text(new, encoding="utf-8")


####################################################################
#
def parse_scenario(raw: dict[str, Any]) -> Scenario:
    """Validate a scenario mapping and build a `Scenario`.

    Args:
        raw: The mapping loaded from YAML.

    Returns:
        The validated scenario.

    Raises:
        ConfigError: If any field is missing or invalid.
    """
    start = _date(raw.get("start"), "start")
    clock = _date(raw.get("clock"), "clock")
    if clock < start:
        raise ConfigError("clock is before start.")

    accounts: list[AccountConfig] = []
    for i, b in enumerate(_list(raw.get("banks"), "banks")):
        bank = _mapping(b, f"banks[{i}]")
        bank_name = _str(bank.get("name"), f"banks[{i}].name")
        for j, a in enumerate(
            _list(bank.get("accounts"), f"banks[{i}].accounts")
        ):
            where = f"banks[{i}].accounts[{j}]"
            accounts.append(_account(_mapping(a, where), bank_name, where))
    if not accounts:
        raise ConfigError("'banks' must hold at least one bank account.")
    keys = [a.key for a in accounts]
    for key in keys:
        if keys.count(key) > 1:
            raise ConfigError(f"Duplicate bank account key {key!r}.")

    scenario = Scenario(
        seed=int(raw.get("seed", 1)),
        owner_email=_str(raw.get("owner"), "owner"),
        start=start,
        clock=clock,
        accounts=tuple(accounts),
        paychecks=tuple(
            _paycheck(_mapping(p, f"paychecks[{i}]"), f"paychecks[{i}]")
            for i, p in enumerate(_list(raw.get("paychecks"), "paychecks"))
        ),
        transfers=tuple(
            _transfer(_mapping(t, f"transfers[{i}]"), f"transfers[{i}]")
            for i, t in enumerate(_list(raw.get("transfers"), "transfers"))
        ),
        bills=tuple(
            _bill(_mapping(b, f"bills[{i}]"), f"bills[{i}]")
            for i, b in enumerate(_list(raw.get("bills"), "bills"))
        ),
        spending=tuple(
            _spending(_mapping(s, f"spending[{i}]"), f"spending[{i}]")
            for i, s in enumerate(_list(raw.get("spending"), "spending"))
        ),
    )
    _check_references(scenario)
    return scenario


####################################################################
#
def _check_references(scenario: Scenario) -> None:
    """Check that every bank account key a section names exists."""
    keys = {a.key for a in scenario.accounts}

    def need(key: str | None, where: str) -> None:
        if key not in keys:
            raise ConfigError(f"{where}: unknown bank account {key!r}.")

    for acct in scenario.accounts:
        if acct.type == "credit_card":
            need(acct.pay_from, f"accounts[{acct.key}].pay_from")
            if scenario.account(acct.pay_from or "").type == "credit_card":
                raise ConfigError(
                    f"accounts[{acct.key}].pay_from must not be a credit card."
                )
    for i, p in enumerate(scenario.paychecks):
        for d in p.deposits:
            need(d.account, f"paychecks[{i}].deposits")
    for i, t in enumerate(scenario.transfers):
        need(t.from_account, f"transfers[{i}].from")
        need(t.to_account, f"transfers[{i}].to")
    for i, b in enumerate(scenario.bills):
        need(b.account, f"bills[{i}].account")
    for s in scenario.spending:
        for key, _ in s.accounts:
            need(key, f"spending[{s.name}].accounts")


####################################################################
#
def _account(raw: dict[str, Any], bank: str, where: str) -> AccountConfig:
    """Build one `AccountConfig`."""
    acct_type = _choice(raw.get("type"), ACCOUNT_TYPES, f"{where}.type")
    number = _str(raw.get("account_number"), f"{where}.account_number")
    if len(number) < 4 or not number[-4:].isdigit():
        raise ConfigError(f"{where}.account_number must end in four digits.")
    is_card = acct_type == "credit_card"
    acct = AccountConfig(
        key=_str(raw.get("key"), f"{where}.key"),
        bank=bank,
        name=_str(raw.get("name"), f"{where}.name"),
        type=acct_type,
        account_number=number,
        opening_balance=_decimal(
            raw.get("opening_balance", "0"), f"{where}.opening_balance"
        ),
        interest_apy=(
            _decimal(raw["interest_apy"], f"{where}.interest_apy")
            if raw.get("interest_apy") is not None
            else None
        ),
        link_aliases=tuple(
            _str(s, f"{where}.link_aliases")
            for s in _list(raw.get("link_aliases"), f"{where}.link_aliases")
        ),
        statement_day=(
            _day(raw.get("statement_day"), f"{where}.statement_day")
            if is_card
            else None
        ),
        payment_day=(
            _day(raw.get("payment_day"), f"{where}.payment_day")
            if is_card
            else None
        ),
        pay_from=raw.get("pay_from") if is_card else None,
    )
    if is_card and acct.opening_balance:
        raise ConfigError(
            f"{where}.opening_balance is not supported on a credit card."
        )
    return acct


####################################################################
#
def _paycheck(raw: dict[str, Any], where: str) -> PaycheckConfig:
    """Build one `PaycheckConfig`."""
    schedule = _choice(
        raw.get("schedule", "semimonthly"),
        PAYCHECK_SCHEDULES,
        f"{where}.schedule",
    )
    anchor = raw.get("anchor")
    if schedule == "biweekly":
        anchor = _date(anchor, f"{where}.anchor")
    net = _decimal(raw.get("net_amount"), f"{where}.net_amount")
    deposits = []
    for i, d in enumerate(_list(raw.get("deposits"), f"{where}.deposits")):
        d = _mapping(d, f"{where}.deposits[{i}]")
        remainder = bool(d.get("remainder", False))
        deposits.append(
            DepositConfig(
                account=_str(d.get("account"), f"{where}.deposits[{i}]"),
                amount=(
                    None
                    if remainder
                    else _decimal(
                        d.get("amount"), f"{where}.deposits[{i}].amount"
                    )
                ),
                remainder=remainder,
            )
        )
    if sum(d.remainder for d in deposits) != 1:
        raise ConfigError(
            f"{where}.deposits needs exactly one 'remainder: true' entry."
        )
    fixed = sum((d.amount or Decimal("0")) for d in deposits)
    if fixed >= net:
        raise ConfigError(
            f"{where}.deposits: the fixed amounts ({fixed}) leave nothing "
            f"of net_amount ({net}) for the remainder."
        )
    return PaycheckConfig(
        employer=_str(raw.get("employer"), f"{where}.employer"),
        schedule=schedule,
        net_amount=net,
        deposits=tuple(deposits),
        anchor=anchor if schedule == "biweekly" else None,
    )


####################################################################
#
def _transfer(raw: dict[str, Any], where: str) -> TransferConfig:
    """Build one `TransferConfig`."""
    return TransferConfig(
        from_account=_str(raw.get("from"), f"{where}.from"),
        to_account=_str(raw.get("to"), f"{where}.to"),
        amount=_amount(raw.get("amount"), f"{where}.amount"),
        day=_day(raw.get("day"), f"{where}.day"),
        lag_days=_int_range(
            raw.get("lag_days", [0, 0]), MAX_LAG_DAYS, f"{where}.lag_days"
        ),
    )


####################################################################
#
def _merchant(raw: dict[str, Any], where: str) -> MerchantConfig:
    """Build one `MerchantConfig`."""
    mcc = raw.get("mcc")
    city = raw.get("city")
    return MerchantConfig(
        name=_str(raw.get("name"), f"{where}.name"),
        city=str(city) if city is not None else None,
        state=raw.get("state"),
        mcc=str(mcc) if mcc is not None else None,
    )


####################################################################
#
def _bill(raw: dict[str, Any], where: str) -> BillConfig:
    """Build one `BillConfig`."""
    method = _choice(raw.get("method", "ach"), BILL_METHODS, f"{where}.method")
    payee = _str(raw.get("payee"), f"{where}.payee")
    return BillConfig(
        payee=payee,
        amount=_amount(raw.get("amount"), f"{where}.amount"),
        day=_day(raw.get("day"), f"{where}.day"),
        account=_str(raw.get("account"), f"{where}.account"),
        method=method,
        category=raw.get("category"),
        merchant=(
            _merchant({**raw, "name": payee}, where)
            if method == "card"
            else None
        ),
    )


####################################################################
#
def _spending(raw: dict[str, Any], where: str) -> SpendingConfig:
    """Build one `SpendingConfig`."""
    name = _str(raw.get("name"), f"{where}.name")
    where = f"spending[{name}]"
    accounts = _mapping(raw.get("accounts"), f"{where}.accounts")
    if not accounts:
        raise ConfigError(f"{where}.accounts must name a bank account.")
    weights = tuple(
        (str(k), _positive_int(v, f"{where}.accounts.{k}"))
        for k, v in accounts.items()
    )
    merchants = tuple(
        _merchant(_mapping(m, f"{where}.merchants[{i}]"), where)
        for i, m in enumerate(_list(raw.get("merchants"), f"{where}.merchants"))
    )
    if not merchants:
        raise ConfigError(f"{where}.merchants must list at least one.")

    tip = raw.get("tip")
    if tip is not None:
        tip = _list(tip, f"{where}.tip")
        if len(tip) != 2 or not 0 <= float(tip[0]) <= float(tip[1]) < 1:
            raise ConfigError(f"{where}.tip must be [min, max] fractions.")
        tip = (float(tip[0]), float(tip[1]))

    per_week = float(raw.get("per_week", 0))
    refund_rate = float(raw.get("refund_rate", 0))
    if per_week < 0 or not 0 <= refund_rate <= 1:
        raise ConfigError(
            f"{where}: per_week must be >= 0 and refund_rate in [0, 1]."
        )

    return SpendingConfig(
        name=name,
        kind=_choice(
            raw.get("kind", "purchase"), SPENDING_KINDS, f"{where}.kind"
        ),
        per_week=per_week,
        amount=_amount(raw.get("amount"), f"{where}.amount"),
        accounts=weights,
        merchants=merchants,
        weekdays=_weekdays(raw.get("weekdays"), f"{where}.weekdays"),
        category=raw.get("category"),
        settle_days=_int_range(
            raw.get("settle_days", [1, 3]),
            MAX_SETTLE_DAYS,
            f"{where}.settle_days",
        ),
        tip=tip,
        refund_rate=refund_rate,
        round_to=(
            _decimal(raw["round_to"], f"{where}.round_to")
            if raw.get("round_to") is not None
            else None
        ),
    )


####################################################################
#
def _weekdays(value: Any, where: str) -> tuple[float, ...]:
    """Parse '{mon: 1, sat: 2}' weights; unnamed days get no spending."""
    if value is None:
        return DEFAULT_WEEKDAY_WEIGHTS
    raw = _mapping(value, where)
    unknown = set(raw) - set(WEEKDAYS)
    if unknown:
        raise ConfigError(
            f"{where}: unknown day(s) {', '.join(sorted(unknown))}; "
            f"use {', '.join(WEEKDAYS)}."
        )
    weights = tuple(float(raw.get(day, 0)) for day in WEEKDAYS)
    if any(w < 0 for w in weights) or not any(weights):
        raise ConfigError(f"{where} needs a positive weight on some day.")
    return weights


####################################################################
#
def _int_range(value: Any, maximum: int, where: str) -> tuple[int, int]:
    """Parse a '[min, max]' day range within 0..maximum."""
    pair = _list(value, where)
    if (
        len(pair) != 2
        or not all(isinstance(n, int) for n in pair)
        or not 0 <= pair[0] <= pair[1] <= maximum
    ):
        raise ConfigError(
            f"{where} must be [min, max] with 0 <= min <= max <= {maximum}."
        )
    return (pair[0], pair[1])


####################################################################
#
def _mapping(value: Any, where: str) -> dict[str, Any]:
    """Require a mapping."""
    if not isinstance(value, dict):
        raise ConfigError(f"{where} must be a mapping.")
    return value


####################################################################
#
def _list(value: Any, where: str) -> list[Any]:
    """Require a list; a missing value is an empty list."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigError(f"{where} must be a list.")
    return value


####################################################################
#
def _str(value: Any, where: str) -> str:
    """Require a non-empty string."""
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{where} is required.")
    return value.strip()


####################################################################
#
def _date(value: Any, where: str) -> date:
    """Require a YYYY-MM-DD date."""
    if not isinstance(value, date):
        raise ConfigError(f"{where} must be a date (YYYY-MM-DD).")
    return value


####################################################################
#
def _choice(value: Any, choices: tuple[str, ...], where: str) -> str:
    """Require one of `choices`."""
    if value not in choices:
        raise ConfigError(f"{where} must be one of {', '.join(choices)}.")
    return value


####################################################################
#
def _positive_int(value: Any, where: str) -> int:
    """Require a positive integer."""
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ConfigError(f"{where} must be a positive integer.")
    return value


####################################################################
#
def _day(value: Any, where: str) -> int:
    """Require a day of the month (days past the month's end clamp)."""
    if not isinstance(value, int) or not 1 <= value <= 31:
        raise ConfigError(f"{where} must be a day of the month (1-31).")
    return value


####################################################################
#
def _decimal(value: Any, where: str) -> Decimal:
    """Require a non-negative decimal amount."""
    if value is None or isinstance(value, bool):
        raise ConfigError(f"{where} is required.")
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise ConfigError(f"{where} must be a number.") from exc
    if not amount.is_finite() or amount < 0:
        raise ConfigError(f"{where} must be a non-negative number.")
    return amount


####################################################################
#
def _amount(value: Any, where: str) -> AmountSpec:
    """Parse a fixed amount or a '[min, max]' range."""
    if isinstance(value, list):
        if len(value) != 2:
            raise ConfigError(f"{where} must be an amount or [min, max].")
        low = _decimal(value[0], where)
        high = _decimal(value[1], where)
        if low > high:
            raise ConfigError(f"{where}: min is larger than max.")
        return AmountSpec(low, high)
    amount = _decimal(value, where)
    return AmountSpec(amount, amount)
