"""
Sanity tests for the importer test factories.

One test per factory: confirms the ``*_factory`` fixture produces an
instance of the expected dataclass with fields populated. Deeper
assertions on generated content live in the parser tests that actually
consume the factory output.
"""

# system imports
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path

# Project imports
from importers.tests.factories import BofaCSVRow, OFXTxnSpec


####################################################################
#
def test_bofa_csv_row_factory_creates_row(
    bofa_csv_row_factory: Callable[..., BofaCSVRow],
) -> None:
    """
    GIVEN: the ``bofa_csv_row_factory`` fixture
    WHEN:  it is invoked with no overrides
    THEN:  a ``BofaCSVRow`` is returned with a faker-generated date,
           description, and negative Decimal amount
    """
    row = bofa_csv_row_factory()

    assert isinstance(row, BofaCSVRow)
    assert isinstance(row.transaction_date, date)
    assert isinstance(row.amount, Decimal)
    assert row.amount < 0  # default factory produces debits
    assert isinstance(row.description, str) and row.description
    assert row.running_balance == Decimal("0.00")


####################################################################
#
def test_bofa_csv_row_factory_respects_overrides(
    bofa_csv_row_factory: Callable[..., BofaCSVRow],
) -> None:
    """
    GIVEN: explicit field overrides
    WHEN:  the factory is called with those kwargs
    THEN:  the resulting row uses the overridden values
    """
    row = bofa_csv_row_factory(
        transaction_date=date(2025, 1, 15),
        amount=Decimal("-42.00"),
        description="TEST MERCHANT",
    )
    assert row.transaction_date == date(2025, 1, 15)
    assert row.amount == Decimal("-42.00")
    assert row.description == "TEST MERCHANT"


####################################################################
#
def test_ofx_txn_spec_factory_creates_spec(
    ofx_txn_spec_factory: Callable[..., OFXTxnSpec],
) -> None:
    """
    GIVEN: the ``ofx_txn_spec_factory`` fixture
    WHEN:  it is invoked with no overrides
    THEN:  an ``OFXTxnSpec`` is returned with default TRNTYPE=POS, a
           negative amount, a faker-generated name, and a unique FITID
    """
    spec = ofx_txn_spec_factory()

    assert isinstance(spec, OFXTxnSpec)
    assert spec.trntype == "POS"
    assert isinstance(spec.amount, Decimal) and spec.amount < 0
    assert isinstance(spec.transaction_date, date)
    assert spec.name
    assert spec.fitid.startswith("FIT")


####################################################################
#
def test_ofx_txn_spec_factory_fitid_is_unique(
    ofx_txn_spec_factory: Callable[..., OFXTxnSpec],
) -> None:
    """
    GIVEN: two factory calls
    WHEN:  FITIDs are generated via ``factory.Sequence``
    THEN:  the two FITIDs differ
    """
    a = ofx_txn_spec_factory()
    b = ofx_txn_spec_factory()
    assert a.fitid != b.fitid


####################################################################
#
def test_bofa_csv_file_factory_writes_valid_file(
    bofa_csv_factory: Callable[..., tuple[Path, list[BofaCSVRow]]],
) -> None:
    """
    GIVEN: the ``bofa_csv_factory`` file-level fixture
    WHEN:  it is invoked
    THEN:  a readable CSV file is written to tmp_path and the returned
           row list has the requested length
    """
    path, rows = bofa_csv_factory(num_transactions=4)
    assert path.exists()
    assert len(rows) == 4
    content = path.read_text()
    assert "Beginning balance" in content
    assert "Date,Description,Amount,Running Bal." in content


####################################################################
#
def test_ofx_file_factory_writes_valid_file(
    ofx_file_factory: Callable[..., tuple[Path, list[OFXTxnSpec]]],
) -> None:
    """
    GIVEN: the ``ofx_file_factory`` file-level fixture
    WHEN:  it is invoked with defaults
    THEN:  an OFX SGML file is written to tmp_path with the expected
           envelope tags and the requested number of STMTTRN blocks
    """
    path, specs = ofx_file_factory(num_transactions=3)
    assert path.exists()
    assert len(specs) == 3
    content = path.read_text()
    assert "OFXHEADER:100" in content
    assert content.count("<STMTTRN>") == 3
    assert "<ACCTID>1234567890" in content
