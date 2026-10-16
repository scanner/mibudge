"""
Generate a new scenario file.

`render_scenario` fills `scenario_template.yaml` with names Faker makes
up: banks, an employer, bill payees, merchants in one home city and
people to send money to.  Faker runs only here.  Once its names are in
the file they never change, which keeps every generated description
stable across Faker upgrades; the simulator reads only the file.
"""

# system imports
#
import json
import re
from collections.abc import Callable
from datetime import date
from importlib import resources
from string import Template

# 3rd party imports
#
from faker import Faker

TEMPLATE_NAME = "scenario_template.yaml"

# Card networks truncate merchant names to about this many characters.
#
_DESCRIPTOR_LEN = 22

# Each merchant line sits under a spending entry's 'merchants:' key.
#
_MERCHANT_INDENT = " " * 6


####################################################################
#
def _q(value: str) -> str:
    """Quote a string for YAML (a JSON string is a YAML string)."""
    return json.dumps(value)


####################################################################
#
def _clean(value: str, limit: int = _DESCRIPTOR_LEN) -> str:
    """Upper-case a name the way a card descriptor shows it."""
    value = re.sub(r"[^A-Z0-9&' -]", "", value.upper())
    return " ".join(value.split())[:limit].strip()


########################################################################
########################################################################
#
class _Names:
    """Faker-made names for one scenario, never repeating."""

    ####################################################################
    #
    def __init__(self, seed: int) -> None:
        self.fake = Faker("en_US")
        self.fake.seed_instance(seed)
        self.used: set[str] = set()

    ####################################################################
    #
    def unique(self, make: Callable[[], str]) -> str:
        """Call `make` until it returns a name not used yet."""
        for _ in range(100):
            name = make()
            if name not in self.used:
                self.used.add(name)
                return name
        raise RuntimeError("Faker ran out of unique names.")

    ####################################################################
    #
    def last(self) -> str:
        """An upper-case surname."""
        return _clean(self.fake.last_name(), 12)

    ####################################################################
    #
    def company(self) -> str:
        """An upper-case company name without its legal suffix."""
        name = re.split(r",| and | LLC| Inc| PLC| Ltd", self.fake.company())[0]
        return _clean(name, 16)

    ####################################################################
    #
    def digits(self, n: int) -> str:
        """`n` random digits."""
        return self.fake.numerify("#" * n)

    ####################################################################
    #
    def phone(self) -> str:
        """A toll-free number, as card descriptors show for online firms."""
        return self.fake.numerify("8%%-555-####")


####################################################################
#
def render_scenario(
    owner_email: str, start: date, clock: date, seed: int
) -> str:
    """Return the text of a new scenario file.

    Args:
        owner_email: The mibudge user who owns the simulated bank accounts.
        start: The first simulated day.
        clock: The simulated "today".
        seed: The scenario's random seed (also seeds Faker here).

    Returns:
        The YAML text, ready to write to a file.
    """
    n = _Names(seed)
    city = _clean(n.fake.city(), 16)
    state = n.fake.state_abbr(include_territories=False)
    nearby = [_clean(n.fake.city(), 16) for _ in range(2)]
    towns = [city, city, *nearby]

    def local(make: Callable[[], str], mcc: str, count: int) -> str:
        """Merchant lines for `count` shops around the home city."""
        lines = []
        for _ in range(count):
            name = n.unique(make)
            town = n.fake.random_element(towns)
            lines.append(
                f"{_MERCHANT_INDENT}- {{name: {_q(name)}, city: {_q(town)}, "
                f'state: {state}, mcc: "{mcc}"}}'
            )
        return "\n".join(lines)

    def remote(make: Callable[[], str], mcc: str, count: int) -> str:
        """Merchant lines for `count` firms known by a phone number."""
        lines = []
        for _ in range(count):
            name = n.unique(make)
            lines.append(
                f"{_MERCHANT_INDENT}- {{name: {_q(name)}, "
                f"city: {_q(n.phone())}, "
                f"state: {n.fake.state_abbr(include_territories=False)}, "
                f'mcc: "{mcc}"}}'
            )
        return "\n".join(lines)

    occasional_mccs = ("5311", "5651", "5942", "5945", "5977", "5992", "7230")
    occasional = "\n".join(
        local(lambda: n.company(), n.fake.random_element(occasional_mccs), 1)
        for _ in range(30)
    )
    friends = "\n".join(
        f"{_MERCHANT_INDENT}- {{name: {_q(_clean(n.fake.name(), 30))}}}"
        for _ in range(4)
    )

    # Last four digits must differ between bank accounts: they are how
    # transfers are linked.
    numbers: list[str] = []
    while len(numbers) < 6:
        number = "99" + n.digits(10)
        if number[-4:] not in {x[-4:] for x in numbers}:
            numbers.append(number)

    bank = f"{n.fake.last_name()} Community Bank"
    card_bank = f"{n.fake.last_name()} Card Services"
    online_bank = f"{n.fake.last_name()} Direct"

    values = {
        "seed": str(seed),
        "owner": _q(owner_email),
        "start": start.isoformat(),
        "clock": clock.isoformat(),
        "bank": _q(bank),
        "card_bank": _q(card_bank),
        "card_bank_alias": _q(f"{card_bank.upper()} DES:EPAY"),
        "online_bank": _q(online_bank),
        "checking_number": _q(numbers[0]),
        "bills_number": _q(numbers[1]),
        "savings_number": _q(numbers[2]),
        "card_number": _q(numbers[3]),
        "travel_card_number": _q(numbers[4]),
        "hysa_number": _q(numbers[5]),
        "employer": _q(f"{n.company()} INC"),
        "city": _q(city),
        "state": state,
        "landlord": _q(f"{n.last()} PROPERTY MGMT"),
        "power": _q(f"{n.last()} POWER & LIGHT"),
        "water": _q(f"{_clean(city, 12)} WATER DEPT"),
        "insurer": _q(f"{n.last()} MUTUAL INS"),
        "phone_co": _q(f"{n.last()} WIRELESS"),
        "isp": _q(f"{n.last()} FIBER"),
        "streaming": _q(f"{n.last()} STREAM"),
        "gym": _q(f"{n.last()} FITNESS"),
        "phone_number_1": _q(n.phone()),
        "phone_number_2": _q(n.phone()),
        "phone_number_3": _q(n.phone()),
        "atm": _q(_clean(f"{bank} ATM", 30)),
        "grocers": local(
            lambda: f"{n.last()} MARKET #{n.digits(4)}", "5411", 3
        ),
        "cafes": local(lambda: f"SQ *{n.last()} COFFEE", "5814", 1)
        + "\n"
        + local(lambda: f"TST* {n.last()} CAFE", "5814", 1),
        "lunch": local(lambda: f"TST* {n.last()} DELI", "5812", 2)
        + "\n"
        + local(lambda: f"SQ *{n.last()} TAQUERIA", "5812", 1),
        "dinner": local(lambda: f"{n.last()} BISTRO", "5812", 2)
        + "\n"
        + local(lambda: f"TST* {n.last()} KITCHEN", "5812", 1),
        "delivery": remote(lambda: f"DD *DOORDASH {n.last()}PIZZA", "5812", 1)
        + "\n"
        + remote(lambda: f"GRUBHUB*{n.last()}", "5812", 1),
        "gas": local(lambda: f"{n.last()} FUEL {n.digits(5)}", "5542", 2),
        "household": local(lambda: f"{n.last()} HARDWARE", "5251", 1)
        + "\n"
        + local(lambda: f"{n.last()} HOME #{n.digits(3)}", "5719", 1),
        "pharmacy": local(lambda: f"{n.last()} DRUG #{n.digits(4)}", "5912", 1),
        "online": remote(lambda: f"{n.last()} MKTP", "5942", 1)
        + "\n"
        + remote(lambda: f"{n.last()}CART.COM", "5399", 1),
        "rideshare": remote(lambda: f"{n.last()} RIDE *TRIP", "4121", 1),
        "occasional": occasional,
        "friends": friends,
    }
    template = Template(
        resources.files("moneypools.simulator")
        .joinpath(TEMPLATE_NAME)
        .read_text(encoding="utf-8")
    )
    return template.substitute(values)
