"""Tests for the BofA CSV and OFX statement parsers."""

# system imports
import logging
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path

# 3rd party imports
import pytest

# Project imports
from importers.parsers import ofx as ofx_parser
from importers.parsers.bofa_csv import (
    _infer_transaction_type,
    parse,
    validate_statement,
)
from importers.tests.factories import OFXTxnSpec


########################################################################
########################################################################
#
class TestBofaCSVParser:
    """Tests for importers.parsers.bofa_csv.parse()."""

    ####################################################################
    #
    @pytest.mark.parametrize("num_transactions", [1, 8, 100])
    def test_transaction_count(
        self,
        num_transactions: int,
        bofa_csv_factory: Callable[..., tuple[Path, list]],
    ) -> None:
        """
        GIVEN: a BofA CSV file with N transactions
        WHEN:  parse() is called
        THEN:  exactly N ParsedTransactions are yielded (summary and
               beginning-balance rows are skipped)
        """
        path, _ = bofa_csv_factory(num_transactions=num_transactions)
        assert len(parse(path).transactions) == num_transactions

    ####################################################################
    #
    @pytest.mark.parametrize(
        "tx_attr,row_attr",
        [
            ("amount", "amount"),
            ("running_balance", "running_balance"),
            ("transaction_date", "transaction_date"),
        ],
    )
    def test_field_matches_generated_data(
        self,
        tx_attr: str,
        row_attr: str,
        bofa_csv_factory: Callable[..., tuple[Path, list]],
    ) -> None:
        """
        GIVEN: a BofA CSV file generated with known field values
        WHEN:  parse() is called
        THEN:  each transaction's field matches the corresponding generated row
        """
        path, rows = bofa_csv_factory(num_transactions=5)
        for tx, row in zip(parse(path).transactions, rows):
            assert getattr(tx, tx_attr) == getattr(row, row_attr)

    ####################################################################
    #
    def test_all_transactions_are_not_pending(
        self,
        bofa_csv_factory: Callable[..., tuple[Path, list]],
    ) -> None:
        """
        GIVEN: a BofA CSV file (exports are always settled)
        WHEN:  parse() is called
        THEN:  every transaction has pending=False
        """
        path, _ = bofa_csv_factory(num_transactions=5)
        for tx in parse(path).transactions:
            assert tx.pending is False

    ####################################################################
    #
    @pytest.mark.parametrize(
        "description,expected_type",
        [
            # Standard purchase
            pytest.param(
                "WIDGETS R US 10/04 PURCHASE EXAMPLE.COM TX",
                "signature_purchase",
                id="purchase",
            ),
            # Mobile purchase via Toast processor (TST* prefix)
            pytest.param(
                "TST*GENERIC EATERY 10/05 MOBILE PURCHASE ANYTOWN CA",
                "signature_purchase",
                id="mobile-purchase-tst",
            ),
            # Purchase via Square processor (SQ * prefix)
            pytest.param(
                "SQ *GENERIC SHOP 10/14 PURCHASE ANYTOWN CA",
                "signature_purchase",
                id="purchase-sq",
            ),
            # ACH direct deposit / payroll (PPD code)
            pytest.param(
                "Acme Corp DES:PAYROLL ID:CER123456 INDN:JOHN DOE CO ID:456 PPD",
                "ach",
                id="ach-payroll-ppd",
            ),
            # ACH corporate debit/credit (CCD code)
            pytest.param(
                "Acme Corp DES:EXPENSE ID:XYZ789 INDN:JANE DOE CO ID:123 CCD",
                "ach",
                id="ach-ccd",
            ),
            # ACH web-initiated payment (WEB code)
            pytest.param(
                "Acme Corp DES:EPAY ID:123456 INDN:JOHN DOE CO ID:789 WEB",
                "ach",
                id="ach-web",
            ),
            # ACH matched via DES: prefix before the class code
            pytest.param(
                "FIRST BANK CREDIT CRD DES:EPAY ID:12345 INDN:JOHN DOE CO ID:67890 WEB",
                "ach",
                id="ach-des-prefix",
            ),
            # Internal transfer between own checking/savings accounts
            pytest.param(
                "Online Banking transfer from CHK 9999 Confirmation# 00000",
                "shared_transfer",
                id="online-transfer",
            ),
            # ATM withdrawal
            pytest.param(
                "ATM WITHDRAWAL 10/10 MAIN ST ANYTOWN CA",
                "atm_withdrawal",
                id="atm-withdrawal",
            ),
            # ATM withdrawal (alternate phrasing)
            pytest.param(
                "ATM CASH WITHDRAWAL 10/12 DOWNTOWN ANYTOWN CA",
                "atm_withdrawal",
                id="atm-cash-withdrawal",
            ),
            # Paper check written against the account
            pytest.param("Check 318", "check", id="check-paper"),
            # Class-action settlement credit paid by the bank
            pytest.param(
                "DOE v EXAMPLEBANK Class Settlement 1-555-000-0000",
                "bank_generated_credit",
                id="class-settlement",
            ),
        ],
    )
    def test_transaction_type_inference(
        self,
        description: str,
        expected_type: str,
    ) -> None:
        """
        GIVEN: a transaction description matching a known BofA pattern
        WHEN:  _infer_transaction_type() is called
        THEN:  the correct TransactionType value is returned
        """
        # Amount sign only matters for the unrecognized-description
        # fallback; for pattern matches a debit amount is fine.
        assert (
            _infer_transaction_type(description, Decimal("-10.00"))
            == expected_type
        )

    ####################################################################
    #
    def test_unrecognized_credit_defaults_to_bank_generated_credit(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """
        GIVEN: a description matching no known pattern and a positive amount
        WHEN:  _infer_transaction_type() is called
        THEN:  "bank_generated_credit" is returned and an INFO message is
               logged
        """
        desc = "SOME UNRECOGNIZED CREDIT WORDING 9999"
        with caplog.at_level(logging.INFO, logger="importers.parsers.bofa_csv"):
            result = _infer_transaction_type(desc, Decimal("42.00"))

        assert result == "bank_generated_credit"
        assert any(desc in r.message for r in caplog.records)

    ####################################################################
    #
    def test_unrecognized_type_returns_not_set_and_logs(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """
        GIVEN: a description matching no known pattern
        WHEN:  _infer_transaction_type() is called
        THEN:  "" (NOT_SET) is returned and an INFO message is logged
               containing the description
        """
        desc = "TOTALLY UNKNOWN DATATOKEN XYZ 9999"
        with caplog.at_level(logging.INFO, logger="importers.parsers.bofa_csv"):
            result = _infer_transaction_type(desc, Decimal("-10.00"))

        assert result == ""
        assert any(desc in r.message for r in caplog.records)
        assert all(r.levelno == logging.INFO for r in caplog.records)

    ####################################################################
    #
    @pytest.mark.parametrize(
        "content,match",
        [
            pytest.param(
                "Description,,Summary Amt.\nFoo,,1.00\n",
                "blank line",
                id="missing-separator",
            ),
            pytest.param(
                "Description,,Summary Amt.\n"
                'Beginning balance as of 01/01/2025,,"1,000.00"\n'
                'Total credits,,"0.00"\n'
                'Total debits,,"0.00"\n'
                'Ending balance as of 01/31/2025,,"1,000.00"\n'
                "\n"
                "Col1,Col2,Col3\n01/01/2025,foo,10.00\n",
                "Unexpected columns",
                id="wrong-columns",
            ),
            pytest.param(
                "Description,,Summary Amt.\nFoo,,1.00\n\n"
                "Date,Description,Amount,Running Bal.\n",
                "missing required row",
                id="missing-summary-rows",
            ),
        ],
    )
    def test_invalid_file_raises(
        self,
        content: str,
        match: str,
        tmp_path: Path,
    ) -> None:
        """
        GIVEN: a malformed BofA CSV file
        WHEN:  parse() is called
        THEN:  ValueError is raised with a descriptive message
        """
        bad_csv = tmp_path / "bad.csv"
        bad_csv.write_text(content)
        with pytest.raises(ValueError, match=match):
            parse(bad_csv)

    ####################################################################
    #
    def test_parse_extracts_summary_metadata(
        self,
        bofa_csv_factory: Callable[..., tuple[Path, list]],
    ) -> None:
        """
        GIVEN: a BofA CSV file with a summary section
        WHEN:  parse() is called
        THEN:  the ParsedStatement surfaces the beginning/ending balances,
               dates, and credit/debit totals derived from the rows.
        """
        from decimal import Decimal

        path, rows = bofa_csv_factory(
            num_transactions=5, beginning_balance="1000.00"
        )
        stmt = parse(path)

        assert stmt.beginning_balance == Decimal("1000.00")
        assert stmt.ending_balance == rows[-1].running_balance
        expected_credits = sum(
            (r.amount for r in rows if r.amount > 0), Decimal("0")
        )
        expected_debits = sum(
            (r.amount for r in rows if r.amount < 0), Decimal("0")
        )
        assert stmt.total_credits == expected_credits
        assert stmt.total_debits == expected_debits

    ####################################################################
    #
    def test_validate_statement_accepts_consistent_file(
        self,
        bofa_csv_factory: Callable[..., tuple[Path, list]],
    ) -> None:
        """
        GIVEN: a BofA CSV whose rows walk cleanly from beginning to ending
               balance and whose summary totals agree
        WHEN:  validate_statement() is called
        THEN:  it returns an empty error list
        """
        path, _ = bofa_csv_factory(num_transactions=8)
        assert validate_statement(parse(path)) == []

    ####################################################################
    #
    def test_validate_statement_flags_running_balance_mismatch(
        self,
        bofa_csv_factory: Callable[..., tuple[Path, list]],
    ) -> None:
        """
        GIVEN: a parsed statement whose first transaction's running
               balance disagrees with the beginning_balance + amount walk
        WHEN:  validate_statement() is called
        THEN:  it returns an error mentioning the running balance
        """
        from decimal import Decimal

        path, _ = bofa_csv_factory(num_transactions=3)
        stmt = parse(path)
        stmt.transactions[0].running_balance += Decimal("100.00")
        errors = validate_statement(stmt)
        assert errors
        assert any("running balance" in e for e in errors)

    ####################################################################
    #
    def test_validate_statement_flags_summary_totals_mismatch(
        self,
        bofa_csv_factory: Callable[..., tuple[Path, list]],
    ) -> None:
        """
        GIVEN: a parsed statement whose summary ending balance does not
               equal beginning + credits + debits
        WHEN:  validate_statement() is called
        THEN:  it returns an error mentioning the summary totals
        """
        from decimal import Decimal

        path, _ = bofa_csv_factory(num_transactions=3)
        stmt = parse(path)
        stmt.ending_balance += Decimal("1.00")
        errors = validate_statement(stmt)
        assert any("Summary totals mismatch" in e for e in errors)


########################################################################
########################################################################
#
class TestOFXParser:
    """Tests for importers.parsers.ofx.parse()."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "ofx_acct_type,expected_code",
        [("CHECKING", "C"), ("SAVINGS", "S")],
    )
    def test_account_id_and_type_surface_on_statement(
        self,
        ofx_acct_type: str,
        expected_code: str,
        ofx_file_factory: Callable[..., tuple[Path, list[OFXTxnSpec]]],
    ) -> None:
        """
        GIVEN: an OFX file with an ACCTID and a known ACCTTYPE
        WHEN:  parse() is called
        THEN:  the ParsedStatement carries acct_id and the mibudge
               account_type code mapped from ACCTTYPE
        """
        path, _ = ofx_file_factory(
            acct_id="9876543210", account_type=ofx_acct_type
        )
        stmt = ofx_parser.parse(path)
        assert stmt.acct_id == "9876543210"
        assert stmt.account_type == expected_code

    ####################################################################
    #
    def test_beginning_balance_derived_from_ending_and_sum(
        self,
        ofx_file_factory: Callable[..., tuple[Path, list[OFXTxnSpec]]],
        ofx_txn_spec_factory: Callable[..., OFXTxnSpec],
    ) -> None:
        """
        GIVEN: an OFX file whose LEDGERBAL is known and whose transactions
               sum to a known amount
        WHEN:  parse() is called
        THEN:  beginning_balance == ending_balance - sum(amounts)
        """
        specs = [
            ofx_txn_spec_factory(
                amount=Decimal("-40.00"), transaction_date=date(2025, 6, 1)
            ),
            ofx_txn_spec_factory(
                amount=Decimal("-60.00"), transaction_date=date(2025, 6, 2)
            ),
            ofx_txn_spec_factory(
                amount=Decimal("200.00"),
                trntype="DEP",
                transaction_date=date(2025, 6, 3),
            ),
        ]
        path, _ = ofx_file_factory(
            specs=specs,
            ending_balance=Decimal("1100.00"),
            start_date=date(2025, 6, 1),
            end_date=date(2025, 6, 30),
        )
        stmt = ofx_parser.parse(path)
        # 1100 - (-40 + -60 + 200) = 1100 - 100 = 1000
        assert stmt.beginning_balance == Decimal("1000.00")
        assert stmt.ending_balance == Decimal("1100.00")

    ####################################################################
    #
    @pytest.mark.parametrize(
        "trntype,expected",
        [
            ("POS", "signature_purchase"),
            ("ATM", "atm_withdrawal"),
            ("CHECK", "check"),
            ("INT", "interest_credit"),
            ("FEE", "fee"),
            ("XFER", "shared_transfer"),
            ("DEP", "check_deposit"),
            ("PAYMENT", "bill_payment"),
            ("DIRECTDEP", "ach"),
            ("DIRECTDEBIT", "ach"),
        ],
    )
    def test_trntype_maps_to_expected_transaction_type(
        self,
        trntype: str,
        expected: str,
        ofx_file_factory: Callable[..., tuple[Path, list[OFXTxnSpec]]],
        ofx_txn_spec_factory: Callable[..., OFXTxnSpec],
    ) -> None:
        """
        GIVEN: an OFX transaction with a specific TRNTYPE
        WHEN:  parse() runs
        THEN:  the ParsedTransaction carries the mibudge-mapped type
        """
        spec = ofx_txn_spec_factory(trntype=trntype)
        path, _ = ofx_file_factory(specs=[spec])
        stmt = ofx_parser.parse(path)
        assert stmt.transactions[0].transaction_type == expected

    ####################################################################
    #
    def test_check_description_includes_checknum(
        self,
        ofx_file_factory: Callable[..., tuple[Path, list[OFXTxnSpec]]],
        ofx_txn_spec_factory: Callable[..., OFXTxnSpec],
    ) -> None:
        """
        GIVEN: an OFX CHECK transaction with a CHECKNUM
        WHEN:  parse() builds the description
        THEN:  the description starts with "Check <num>"
        """
        spec = ofx_txn_spec_factory(
            trntype="CHECK",
            checknum="318",
            name="PAPER CHECK",
            amount=Decimal("-125.00"),
        )
        path, _ = ofx_file_factory(specs=[spec])
        desc = ofx_parser.parse(path).transactions[0].raw_description
        assert desc.startswith("Check 318")

    ####################################################################
    #
    def test_validate_statement_accepts_derived_walk(
        self,
        ofx_file_factory: Callable[..., tuple[Path, list[OFXTxnSpec]]],
    ) -> None:
        """
        GIVEN: an OFX file whose running balances are derived by the parser
        WHEN:  validate_statement() is called
        THEN:  the walk is clean (empty error list) -- the check is
               tautological by construction but guarantees uniform shape
        """
        path, _ = ofx_file_factory(num_transactions=5)
        assert ofx_parser.validate_statement(ofx_parser.parse(path)) == []

    ####################################################################
    #
    def test_empty_or_malformed_file_raises(self, tmp_path: Path) -> None:
        """
        GIVEN: a file that is not a recognisable OFX statement
        WHEN:  parse() is called
        THEN:  ValueError is raised
        """
        bad = tmp_path / "not_ofx.ofx"
        bad.write_text("this is not OFX content at all\n")
        with pytest.raises(ValueError):
            ofx_parser.parse(bad)
