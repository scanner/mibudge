"""
Bank activity generator.

`simulate` plays a scenario's financial life forward one day at a time
from its `start` and returns every transaction that has happened by
`through`.  The result is a pure function of the scenario, the owner's
name and `through`: each day's choices come from a `random.Random`
seeded with '<seed>:<stream>:<day>', so a transaction dated D is the
same on every run whose `through` is D or later.  Only whether it is
still pending (and so which amount and description the bank shows)
depends on `through`.

That stability is what lets the management command re-send a trailing
window of transactions on every run: rows mibudge already has dedup on
(transaction date, amount, description), and pending rows are replaced
wholesale, exactly as with a live bank scrape.  Every generated posted
row is therefore kept unique on that key.

Settlement follows the Federal Reserve calendar (`holidays`): paydays
move to the business day before, ACH debits and card settlement to the
business day after.

Signs follow the bank: money leaving a bank account is negative,
including purchases on a credit card, whose balance is negative while
money is owed on it.
"""

# system imports
#
import calendar
import math
import random
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

# Project imports
#
from moneypools.models import Transaction

from .config import (
    AccountConfig,
    AmountSpec,
    BillConfig,
    MerchantConfig,
    Scenario,
    SpendingConfig,
)
from .holidays import next_business_day, previous_business_day

CENT = Decimal("0.01")
TxType = Transaction.TransactionType

# A refund lands this many days after the purchase.
#
_REFUND_DELAY = (3, 12)

# How a bank account is named in a transfer description.
#
_KIND = {"checking": "CHK", "savings": "SAV", "credit_card": "CRD"}


########################################################################
########################################################################
#
@dataclass(frozen=True)
class SimTransaction:
    """One generated bank transaction.

    `purchase_date` is when it happened and `settle_date` when it
    posts; they are equal for anything that posts at once.  While it is
    pending the bank shows `pending_amount` and `pending_description`.
    """

    account: str
    purchase_date: date
    settle_date: date
    posted_description: str
    posted_amount: Decimal
    transaction_type: str
    pending_description: str = ""
    pending_amount: Decimal | None = None
    category: str | None = None
    details: dict[str, Any] | None = None

    ####################################################################
    #
    def is_pending(self, through: date) -> bool:
        """True when the transaction has not posted by `through`."""
        return self.settle_date > through

    ####################################################################
    #
    def amount_at(self, through: date) -> Decimal:
        """The amount the bank shows on `through`."""
        if self.is_pending(through) and self.pending_amount is not None:
            return self.pending_amount
        return self.posted_amount

    ####################################################################
    #
    def description_at(self, through: date) -> str:
        """The description the bank shows on `through`."""
        if self.is_pending(through) and self.pending_description:
            return self.pending_description
        return self.posted_description


####################################################################
#
def simulate(
    scenario: Scenario, owner_name: str, through: date
) -> list[SimTransaction]:
    """Generate every transaction from the scenario's start to `through`.

    Args:
        scenario: The scenario to play.
        owner_name: The account holder's name, as it appears in payroll
            and bill-pay descriptions.
        through: The last simulated day.

    Returns:
        The transactions dated on or before `through`, in date order.
    """
    sim = _Simulation(scenario, owner_name.upper())
    sim.run(scenario.start, through)
    return sorted(
        (t for t in sim.txns if t.purchase_date <= through),
        key=lambda t: (t.purchase_date, t.settle_date),
    )


####################################################################
#
def as_of(txns: list[SimTransaction], through: date) -> list[SimTransaction]:
    """The part of a simulation that has happened by `through`.

    `simulate(s, n, later)` filtered with `as_of(..., d)` equals
    `simulate(s, n, d)`, so one simulation serves every day of an
    advance.
    """
    return [t for t in txns if t.purchase_date <= through]


####################################################################
#
def ending_balance(
    txns: list[SimTransaction], account: str, through: date
) -> Decimal:
    """The available balance of one bank account on `through`."""
    return sum(
        (
            t.amount_at(through)
            for t in txns
            if t.account == account and t.purchase_date <= through
        ),
        Decimal("0"),
    )


########################################################################
########################################################################
#
@dataclass
class _Simulation:
    """The running state of one simulation."""

    scenario: Scenario
    owner: str
    txns: list[SimTransaction] = field(default_factory=list)
    # Posted balance per bank account through the end of the previous
    # day, and amounts that post on a future day.
    posted: dict[str, Decimal] = field(default_factory=dict)
    settling: dict[date, dict[str, Decimal]] = field(default_factory=dict)
    # The statement balance owed on each credit card.
    statement: dict[str, Decimal] = field(default_factory=dict)
    _keys: set[tuple[str, date, Decimal, str]] = field(default_factory=set)

    ####################################################################
    #
    def run(self, start: date, through: date) -> None:
        """Play every day from `start` through `through`."""
        self.posted = {a.key: Decimal("0") for a in self.scenario.accounts}
        for acct in self.scenario.accounts:
            if acct.opening_balance > 0:
                self._immediate(
                    acct.key,
                    start,
                    "OPENING DEPOSIT",
                    acct.opening_balance,
                    TxType.BANK_GENERATED_CREDIT,
                    None,
                )

        day = start
        while day <= through:
            self._paychecks(day)
            self._transfers(day)
            self._bills(day)
            for spend in self.scenario.spending:
                self._spend(spend, day)
            self._interest(day)
            self._card_cycle(day)
            for key, amount in self.settling.pop(day, {}).items():
                self.posted[key] += amount
            day += timedelta(days=1)

    ####################################################################
    #
    def _rng(self, stream: str, day: date) -> random.Random:
        """The random source for one stream of choices on one day."""
        return random.Random(f"{self.scenario.seed}:{stream}:{day.isoformat()}")

    ####################################################################
    #
    def _posted_on(self, key: str, day: date) -> Decimal:
        """A bank account's posted balance at the end of `day`."""
        return self.posted[key] + self.settling.get(day, {}).get(
            key, Decimal("0")
        )

    ####################################################################
    #
    def _add(self, txn: SimTransaction) -> None:
        """Record a transaction, nudging its amount until it is unique.

        mibudge dedups posted rows on (transaction date, amount,
        description); two identical purchases on one day would collapse
        into one, so the later one is a cent smaller.
        """
        while True:
            key = (
                txn.account,
                txn.purchase_date,
                txn.posted_amount,
                txn.posted_description,
            )
            if key not in self._keys:
                break
            txn = replace(
                txn,
                posted_amount=txn.posted_amount - CENT,
                pending_amount=(
                    txn.pending_amount - CENT
                    if txn.pending_amount is not None
                    else None
                ),
            )
        self._keys.add(key)
        self.txns.append(txn)
        bucket = self.settling.setdefault(txn.settle_date, {})
        bucket[txn.account] = (
            bucket.get(txn.account, Decimal("0")) + txn.posted_amount
        )

    ####################################################################
    #
    def _immediate(
        self,
        account: str,
        day: date,
        desc: str,
        amount: Decimal,
        tx_type: str,
        category: str | None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record a transaction that posts the day it happens."""
        self._add(
            SimTransaction(
                account=account,
                purchase_date=day,
                settle_date=day,
                posted_description=desc,
                posted_amount=amount,
                transaction_type=tx_type,
                category=category,
                details=details,
            )
        )

    ####################################################################
    #
    def _paychecks(self, day: date) -> None:
        """Deposit any paycheck paid on `day`, split across bank accounts."""
        for pay in self.scenario.paychecks:
            if pay.schedule == "semimonthly":
                paid = _hits_monthly(day, 15, "back") or _hits_monthly(
                    day, 31, "back"
                )
            else:
                assert pay.anchor is not None
                anchor = pay.anchor
                paid = any(
                    (day + timedelta(n) - anchor).days % 14 == 0
                    and previous_business_day(day + timedelta(n)) == day
                    for n in range(7)
                )
            if not paid:
                continue
            rng = self._rng(f"pay:{pay.employer}", day)
            ref = _digits(rng, 10)
            company = _digits(rng, 10)
            fixed = sum((d.amount or Decimal("0")) for d in pay.deposits)
            for dep in pay.deposits:
                amount = pay.net_amount - fixed if dep.remainder else dep.amount
                assert amount is not None
                self._immediate(
                    dep.account,
                    day,
                    f"{pay.employer} DES:PAYROLL ID:{ref} "
                    f"INDN:{self.owner} CO ID:{company} PPD",
                    amount,
                    TxType.ACH,
                    "Income : Paycheck",
                    {"merchant_name": pay.employer.title()},
                )

    ####################################################################
    #
    def _transfers(self, day: date) -> None:
        """Make any transfer between the bank accounts due on `day`.

        Within one bank the money moves at once.  Between banks it
        leaves on `day` and arrives `lag_days` later (on a business
        day).
        """
        for i, xfer in enumerate(self.scenario.transfers):
            if not _hits_monthly(day, xfer.day, "forward"):
                continue
            rng = self._rng(f"transfer:{i}", day)
            amount = _draw(rng, xfer.amount)
            src = self.scenario.account(xfer.from_account)
            dst = self.scenario.account(xfer.to_account)
            conf = _digits(rng, 9)
            if src.bank == dst.bank:
                arrives = day
                label = "ONLINE BANKING TRANSFER"
                to_where, from_where = _KIND[dst.type], _KIND[src.type]
            else:
                arrives = next_business_day(
                    day + timedelta(rng.randint(*xfer.lag_days))
                )
                label = "EXTERNAL TRANSFER"
                to_where, from_where = dst.bank.upper(), src.bank.upper()
            category = "Financial : Money Transfers"
            self._immediate(
                src.key,
                day,
                f"{label} TO {to_where} ENDING IN {dst.last4} CONF# {conf}",
                -amount,
                TxType.ACH,
                category,
            )
            self._immediate(
                dst.key,
                arrives,
                f"{label} FROM {from_where} ENDING IN {src.last4} CONF# {conf}",
                amount,
                TxType.ACH,
                category,
            )

    ####################################################################
    #
    def _bills(self, day: date) -> None:
        """Pay any bill due on `day`."""
        for bill in self.scenario.bills:
            if bill.method == "card":
                if _hits_monthly(day, bill.day, None):
                    self._bill_by_card(bill, day)
                continue
            if not _hits_monthly(day, bill.day, "forward"):
                continue
            rng = self._rng(f"bill:{bill.payee}", day)
            self._immediate(
                bill.account,
                day,
                f"{bill.payee} DES:BILL PAY ID:{_digits(rng, 11)} "
                f"INDN:{self.owner} WEB",
                -_draw(rng, bill.amount),
                TxType.BILL_PAYMENT,
                bill.category,
                {"merchant_name": bill.payee.title()},
            )

    ####################################################################
    #
    def _bill_by_card(self, bill: BillConfig, day: date) -> None:
        """Charge a monthly bill to a card like any purchase."""
        assert bill.merchant is not None
        rng = self._rng(f"bill:{bill.payee}", day)
        amount = _draw(rng, bill.amount)
        self._purchase(
            rng,
            bill.account,
            bill.merchant,
            day,
            amount,
            amount,
            (1, 2),
            bill.category,
        )

    ####################################################################
    #
    def _spend(self, spend: SpendingConfig, day: date) -> None:
        """Generate one kind of everyday spending for `day`."""
        rng = self._rng(f"spend:{spend.name}", day)
        weights = spend.weekdays
        rate = spend.per_week * weights[day.weekday()] / sum(weights)
        for _ in range(_poisson(rng, rate)):
            account = _weighted(rng, spend.accounts)
            merchant = rng.choice(spend.merchants)
            amount = _draw(rng, spend.amount, spend.round_to)
            match spend.kind:
                case "atm":
                    self._immediate(
                        account,
                        day,
                        f"{merchant.name} {day:%m/%d} #{_digits(rng, 9)} "
                        f"WITHDRWL {_place(merchant)}",
                        -amount,
                        TxType.ATM_WITHDRAWAL,
                        spend.category,
                    )
                case "zelle":
                    self._immediate(
                        account,
                        day,
                        f"ZELLE PAYMENT TO {merchant.name} "
                        f"CONF# {_alnum(rng, 9)}",
                        -amount,
                        TxType.C2C,
                        spend.category,
                    )
                case _:
                    posted = amount
                    if spend.tip is not None:
                        posted = _cents(
                            amount * Decimal(str(1 + rng.uniform(*spend.tip)))
                        )
                    self._purchase(
                        rng,
                        account,
                        merchant,
                        day,
                        amount,
                        posted,
                        spend.settle_days,
                        spend.category,
                    )
                    if rng.random() < spend.refund_rate:
                        self._refund(rng, account, merchant, day, posted, spend)

    ####################################################################
    #
    def _purchase(
        self,
        rng: random.Random,
        account: str,
        merchant: MerchantConfig,
        day: date,
        authorized: Decimal,
        posted: Decimal,
        settle_days: tuple[int, int],
        category: str | None,
    ) -> None:
        """Record a card purchase that is pending until it settles."""
        settle = next_business_day(day + timedelta(rng.randint(*settle_days)))
        place = _place(merchant)
        self._add(
            SimTransaction(
                account=account,
                purchase_date=day,
                settle_date=settle,
                posted_description=(
                    f"{merchant.name} {day:%m/%d} PURCHASE {place}".strip()
                ),
                posted_amount=-posted,
                pending_description=(
                    f"PURCHASE {day:%m/%d} {merchant.name} {place}".strip()
                ),
                pending_amount=-authorized,
                transaction_type=TxType.SIGNATURE_PURCHASE,
                category=category,
                details=_merchant_details(merchant, category),
            )
        )

    ####################################################################
    #
    def _refund(
        self,
        rng: random.Random,
        account: str,
        merchant: MerchantConfig,
        day: date,
        amount: Decimal,
        spend: SpendingConfig,
    ) -> None:
        """Refund a purchase some days after it was made."""
        when = day + timedelta(rng.randint(*_REFUND_DELAY))
        settle = next_business_day(when + timedelta(rng.randint(1, 2)))
        place = _place(merchant)
        self._add(
            SimTransaction(
                account=account,
                purchase_date=when,
                settle_date=settle,
                posted_description=(
                    f"{merchant.name} {when:%m/%d} REFUND {place}".strip()
                ),
                posted_amount=amount,
                pending_description=(
                    f"REFUND {when:%m/%d} {merchant.name} {place}".strip()
                ),
                pending_amount=amount,
                transaction_type=TxType.SIGNATURE_RETURN,
                category=spend.category,
                details=_merchant_details(merchant, spend.category),
            )
        )

    ####################################################################
    #
    def _interest(self, day: date) -> None:
        """Credit savings interest on the last day of the month."""
        if day.day != calendar.monthrange(day.year, day.month)[1]:
            return
        for acct in self.scenario.accounts:
            if not acct.interest_apy:
                continue
            balance = self._posted_on(acct.key, day)
            interest = _cents(balance * acct.interest_apy / 100 / 12)
            if interest > 0:
                self._immediate(
                    acct.key,
                    day,
                    "INTEREST EARNED",
                    interest,
                    TxType.INTEREST_CREDIT,
                    "Income : Interest",
                )

    ####################################################################
    #
    def _card_cycle(self, day: date) -> None:
        """Close credit card statements and pay them when due."""
        for card in self.scenario.accounts:
            if card.type != "credit_card":
                continue
            assert card.statement_day and card.payment_day and card.pay_from
            if _hits_monthly(day, card.payment_day, "forward"):
                owed = self.statement.pop(card.key, Decimal("0"))
                if owed > 0:
                    self._card_payment(card, day, owed)
            if _hits_monthly(day, card.statement_day, None):
                self.statement[card.key] = max(
                    Decimal("0"), -self._posted_on(card.key, day)
                )

    ####################################################################
    #
    def _card_payment(
        self, card: AccountConfig, day: date, owed: Decimal
    ) -> None:
        """Pay a card's statement balance from its paying bank account.

        A card at the same bank names the card's last four digits.  A
        card at another bank shows up the way an issuer's e-payment
        does, which links through the card's `link_aliases`.
        """
        assert card.pay_from is not None
        src = self.scenario.account(card.pay_from)
        ref = _digits(self._rng(f"card:{card.key}", day), 10)
        category = "Financial : Credit Card Payment"
        if src.bank == card.bank:
            src_desc = (
                f"{card.bank.upper()} CREDIT CARD DES:PAYMENT ID:{ref} "
                f"ENDING IN {card.last4}"
            )
            card_desc = (
                f"PAYMENT - THANK YOU FROM {_KIND[src.type]} "
                f"ENDING IN {src.last4} REF {ref}"
            )
        else:
            src_desc = (
                f"{card.bank.upper()} DES:EPAY ID:{ref} INDN:{self.owner} WEB"
            )
            card_desc = f"ONLINE PAYMENT RECEIVED - THANK YOU REF {ref}"
        self._immediate(src.key, day, src_desc, -owed, TxType.ACH, category)
        self._immediate(card.key, day, card_desc, owed, TxType.ACH, category)


####################################################################
#
def _merchant_details(
    merchant: MerchantConfig, category: str | None
) -> dict[str, Any]:
    """The merchant details record a bank would show for a purchase."""
    details: dict[str, Any] = {"merchant_name": merchant.name.title()}
    if merchant.city and merchant.state:
        details["merchant_information"] = f"{merchant.city}, {merchant.state}"
    if merchant.mcc:
        details["merchant_category_code"] = merchant.mcc
    if category and " : " in category:
        details["merchant_category"] = category.split(" : ", 1)[1]
    return details


####################################################################
#
def _place(merchant: MerchantConfig) -> str:
    """The 'CITY ST' suffix a card description carries."""
    return " ".join(p for p in (merchant.city, merchant.state) if p)


####################################################################
#
def _hits_monthly(day: date, dom: int, roll: str | None) -> bool:
    """True when a monthly event on day-of-month `dom` lands on `day`.

    A `dom` past the end of a month means that month's last day.  When
    the scheduled date is not a business day, `roll='back'` moves it to
    the business day before (paydays), `roll='forward'` to the one
    after (ACH debits), and `roll=None` leaves it (card charges happen
    any day).
    """
    for offset in (-1, 0, 1):
        year, month = divmod(day.year * 12 + day.month - 1 + offset, 12)
        month += 1
        scheduled = date(
            year, month, min(dom, calendar.monthrange(year, month)[1])
        )
        match roll:
            case "back":
                scheduled = previous_business_day(scheduled)
            case "forward":
                scheduled = next_business_day(scheduled)
        if scheduled == day:
            return True
    return False


####################################################################
#
def _cents(value: Decimal) -> Decimal:
    """Round to cents."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


####################################################################
#
def _draw(
    rng: random.Random, spec: AmountSpec, round_to: Decimal | None = None
) -> Decimal:
    """Pick an amount from `spec`, weighted towards the low end."""
    if spec.fixed:
        return spec.low
    low, high = float(spec.low), float(spec.high)
    value = Decimal(str(rng.triangular(low, high, low + (high - low) / 4)))
    if round_to:
        steps = max(1, int((value / round_to).to_integral_value()))
        return _cents(round_to * steps)
    return _cents(value)


####################################################################
#
def _poisson(rng: random.Random, rate: float) -> int:
    """Draw from a Poisson distribution with mean `rate` (Knuth)."""
    if rate <= 0:
        return 0
    limit = math.exp(-rate)
    count, product = 0, rng.random()
    while product > limit:
        count += 1
        product *= rng.random()
    return count


####################################################################
#
def _weighted(rng: random.Random, choices: tuple[tuple[str, int], ...]) -> str:
    """Pick a key from (key, weight) pairs."""
    keys = [k for k, _ in choices]
    return rng.choices(keys, weights=[w for _, w in choices])[0]


####################################################################
#
def _digits(rng: random.Random, n: int) -> str:
    """An `n`-digit reference number."""
    return "".join(rng.choice("0123456789") for _ in range(n))


####################################################################
#
def _alnum(rng: random.Random, n: int) -> str:
    """An `n`-character uppercase alphanumeric confirmation code."""
    return "".join(
        rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(n)
    )
