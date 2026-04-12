"""Tests for the BofA CSV parser."""

# system imports
import logging
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

# 3rd party imports
import pytest

# Project imports
from importers.parsers.bofa_csv import (
    _infer_transaction_type,
    parse,
    validate_statement,
)


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
