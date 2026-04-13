"""
factory_boy factories for importer test fixtures.

Each factory here produces one *row* / *transaction*. Higher-level
orchestration (writing a full BofA CSV with walked running balances,
writing a multi-transaction OFX file) lives in ``conftest.py``
fixtures that consume these factories -- factory_boy is the right
tool for building model instances with faker-driven defaults, while
tmp_path file writing and balance-walk invariants are fixture
concerns.

Factories are registered in ``conftest.py`` via
``pytest_factoryboy.register()``, which exposes each as a snake_case
fixture (``bofa_csv_row_factory`` for ``BofaCSVRowFactory``). Tests
prefer the ``*_factory`` fixture over calling the factory class
directly (see the project testing guide in ``CLAUDE.md``).
"""

# system imports
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

# 3rd party imports
import factory
from faker import Faker

# Module-level Faker used inside ``factory.lazy_attribute`` callbacks
# that need to compose multiple faker fields into one string. factory_boy
# has no built-in helper for composed strings that span multiple
# providers, so using a local Faker is the pragmatic path.
_fake = Faker()


########################################################################
########################################################################
#
@dataclass
class BofaCSVRow:
    """
    One generated Bank of America CSV transaction row.

    The ``running_balance`` is filled in by the ``bofa_csv_factory``
    fixture as it walks the statement; the factory defaults it to
    ``Decimal("0")`` since per-row factories have no knowledge of the
    statement-level balance.
    """

    transaction_date: date
    description: str
    amount: Decimal
    running_balance: Decimal


# BofA description templates: each callable takes a Faker instance
# and produces a realistic-looking raw_description covering one of
# the transaction types the parser knows how to classify. Kept
# alongside the factory so "what a realistic row looks like" lives in
# one place.
_BOFA_DESCRIPTION_TEMPLATES = [
    lambda f: (
        f"{f.company().upper()} "
        f"{f.past_date(start_date='-30d'):%m/%d} PURCHASE "
        f"{f.city().upper()} {f.state_abbr()}"
    ),
    lambda f: (
        f"TST*{f.company().upper()} "
        f"{f.past_date(start_date='-30d'):%m/%d} MOBILE PURCHASE "
        f"{f.city().upper()} {f.state_abbr()}"
    ),
    lambda f: (
        f"SQ *{f.company().upper()} "
        f"{f.past_date(start_date='-30d'):%m/%d} PURCHASE "
        f"{f.city().upper()} {f.state_abbr()}"
    ),
    lambda f: (
        f"{f.company()} DES:PAYROLL ID:CER{f.numerify('######')} "
        f"INDN:{f.name().upper()} CO ID:{f.numerify('######')} PPD"
    ),
    lambda f: (
        f"{f.company()} DES:{f.bothify('??-######')} "
        f"ID:{f.bothify('??????????')} INDN:{f.name().upper()} "
        f"CO ID:{f.numerify('######')} CCD"
    ),
    lambda f: (
        f"Online Banking transfer from CHK {f.numerify('####')} "
        f"Confirmation# {f.numerify('#####')}"
    ),
    lambda f: (
        f"ATM WITHDRAWAL {f.past_date(start_date='-30d'):%m/%d} "
        f"{f.city().upper()} {f.state_abbr()}"
    ),
]


########################################################################
########################################################################
#
class BofaCSVRowFactory(factory.Factory):
    """
    Factory for a single ``BofaCSVRow``.

    Defaults produce a small debit ($1.00 -- $200.00) with a realistic
    description from the pattern library. Tests pass ``amount=`` /
    ``transaction_date=`` / ``description=`` to pin specific values.
    ``running_balance`` defaults to zero; the ``bofa_csv_factory``
    fixture overwrites it after walking the statement.
    """

    class Meta:
        model = BofaCSVRow

    transaction_date = factory.Faker(
        "date_between", start_date="-90d", end_date="today"
    )
    amount = factory.Faker(
        "pydecimal", min_value=-200, max_value=-1, right_digits=2
    )
    running_balance = Decimal("0.00")

    @factory.lazy_attribute
    def description(self) -> str:
        template = _fake.random_element(_BOFA_DESCRIPTION_TEMPLATES)
        return template(_fake)


########################################################################
########################################################################
#
@dataclass
class OFXTxnSpec:
    """
    Declarative spec for a synthetic OFX transaction.

    Consumed by the ``ofx_file_factory`` fixture, which serializes a
    list of specs into the SGML form the OFX parser expects. Kept as
    a dataclass (not a NamedTuple) so factory_boy can populate it via
    keyword arguments.
    """

    transaction_date: date
    amount: Decimal
    trntype: str
    name: str
    memo: str = ""
    checknum: str = ""
    fitid: str = ""


########################################################################
########################################################################
#
class OFXTxnSpecFactory(factory.Factory):
    """
    Factory for a single ``OFXTxnSpec``.

    Defaults produce a small TRNTYPE=POS debit with a faker-generated
    merchant name and a unique FITID per call. Override any field to
    build targeted scenarios (CHECK with a checknum, INT credit, etc.).

    Examples::

        ofx_txn_spec_factory()                                    # default POS debit
        ofx_txn_spec_factory(trntype="CHECK", checknum="318",
                             amount=Decimal("-100.00"))
        ofx_txn_spec_factory(trntype="INT", amount=Decimal("1.23"))
    """

    class Meta:
        model = OFXTxnSpec

    transaction_date = factory.Faker(
        "date_between", start_date="-30d", end_date="today"
    )
    amount = factory.Faker(
        "pydecimal", min_value=-200, max_value=-1, right_digits=2
    )
    trntype = "POS"
    name = factory.Faker("company")
    memo = ""
    checknum = ""
    fitid = factory.Sequence(lambda n: f"FIT{n:010d}")
