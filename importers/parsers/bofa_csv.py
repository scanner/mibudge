"""
Bank of America CSV transaction parser.

Unrecognized transaction type patterns are logged at INFO level using the
module logger (``importers.parsers.bofa_csv``).  The transaction is still
imported correctly with transaction_type set to NOT_SET ("") -- nothing is
lost.  The import script also prints a deduplicated summary of unrecognized
descriptions after processing so they can be used to extend the pattern list
and re-run the import to backfill the type on those transactions.

BofA CSV exports have two sections separated by a blank line:

    Description,,Summary Amt.
    Beginning balance as of MM/DD/YYYY,,"N,NNN.NN"
    Total credits,,"N,NNN.NN"
    Total debits,,"-N,NNN.NN"
    Ending balance as of MM/DD/YYYY,,"N,NNN.NN"

    Date,Description,Amount,Running Bal.
    MM/DD/YYYY,Beginning balance as of ...,,"N,NNN.NN"
    MM/DD/YYYY,"MERCHANT NAME ...","-NN.NN","N,NNN.NN"
    ...

This format is the same for both checking and savings accounts. All exported
transactions are settled (never pending).

The parser yields ParsedTransaction dataclasses. Transaction type is inferred
from description keywords; anything unrecognised is left as NOT_SET ("").
"""

# system imports
import csv
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

logger = logging.getLogger(__name__)


########################################################################
########################################################################
#
@dataclass
class ParsedTransaction:
    """
    A single transaction extracted from a BofA CSV export.

    Args:
        transaction_date: Settlement date (no time component in CSV exports).
        raw_description:  Description string exactly as it appears in the CSV.
        amount:           Signed decimal amount. Negative = debit, positive = credit.
        running_balance:  Account running balance after this transaction.
        transaction_type: One of Transaction.TransactionType values, or "" (NOT_SET).
        pending:          Always False -- CSV exports contain only settled transactions.
    """

    transaction_date: date
    raw_description: str
    amount: Decimal
    running_balance: Decimal
    transaction_type: str
    pending: bool = False


########################################################################
########################################################################
#
# Keyword patterns for transaction type inference from BofA descriptions.
# Checked in order; first match wins.
#
# BofA descriptions follow several conventions worth noting:
#
# Payment processor prefixes -- a merchant name may be prefixed with the
# payment processor name and a "*" separator, e.g.:
#   TST*TASTY FOODS       (Toast -- table-service restaurants)
#   SQ *MERCHANT NAME        (Square -- small merchants, coffee shops)
#   GRUBHUB*MERCHANT NAME    (Grubhub)
# These are all still PURCHASE transactions; the prefix is useful for
# merchant extraction but does not change the transaction type.
#
# ACH Standard Entry Class codes appear at the end of ACH entries:
#   PPD  Prearranged Payment and Deposit (direct deposit/payroll)
#   CCD  Corporate Credit or Debit (business payments e.g. expense reimbursement)
#   WEB  Internet-initiated payment
#   TEL  Telephone-initiated
#   ARC  Accounts Receivable Check conversion
#   RCK  Re-presented check entry
#
_TYPE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bATM\b.*\bWITHDRAWAL\b", re.IGNORECASE), "atm_withdrawal"),
    (re.compile(r"\bATM\b", re.IGNORECASE), "atm_withdrawal"),
    # Internal transfer between own bank accounts (e.g. "Online Banking
    # transfer from CHK 2121 Confirmation# ...").
    (
        re.compile(r"\bOnline Banking transfer\b", re.IGNORECASE),
        "shared_transfer",
    ),
    (
        re.compile(r"\b(MOBILE\s+)?PURCHASE\b", re.IGNORECASE),
        "signature_purchase",
    ),
    (re.compile(r"\bPAYROLL\b", re.IGNORECASE), "ach"),
    (re.compile(r"\bDIRECT\s+DEP(OSIT)?\b", re.IGNORECASE), "ach"),
    (re.compile(r"\bWIRE\b", re.IGNORECASE), "wire_transfer"),
    (re.compile(r"\bCHECK\s+DEPOSIT\b", re.IGNORECASE), "check_deposit"),
    (re.compile(r"\bINTEREST\b", re.IGNORECASE), "interest_credit"),
    (re.compile(r"\bSERVICE\s+CHARGE\b|\bFEE\b", re.IGNORECASE), "fee"),
    # ACH transactions -- DES: format is used for structured ACH entries.
    # Standard Entry Class codes (PPD, CCD, WEB, etc.) follow at end.
    (re.compile(r"\bDES:", re.IGNORECASE), "ach"),
    (re.compile(r"\b(PPD|CCD|WEB|TEL|ARC|RCK)\b"), "ach"),
]


####################################################################
#
def _infer_transaction_type(description: str) -> str:
    """
    Infer a TransactionType value from a BofA transaction description.

    Args:
        description: Raw description string from the CSV.

    Returns:
        A TransactionType value string, or "" (NOT_SET) if no pattern matches.
    """
    for pattern, transaction_type in _TYPE_PATTERNS:
        if pattern.search(description):
            return transaction_type
    logger.info("Unrecognized transaction type pattern: %r", description)
    return ""


####################################################################
#
def _parse_amount(raw: str) -> Decimal:
    """
    Parse a BofA amount string into a Decimal.

    BofA amounts are formatted with comma thousands separators and may be
    quoted (handled by the CSV reader before reaching this function).

    Args:
        raw: Amount string, e.g. "-1,234.56" or "2,000.00".

    Returns:
        Decimal representation of the amount.

    Raises:
        ValueError: If the string cannot be parsed as a decimal amount.
    """
    cleaned = raw.replace(",", "").strip()
    try:
        return Decimal(cleaned)
    except InvalidOperation as e:
        raise ValueError(f"Cannot parse amount {raw!r}: {e}") from e


####################################################################
#
def _parse_date(raw: str) -> date:
    """
    Parse a BofA date string (MM/DD/YYYY) into a date object.

    Args:
        raw: Date string in MM/DD/YYYY format.

    Returns:
        Parsed date.

    Raises:
        ValueError: If the string does not match MM/DD/YYYY.
    """
    return datetime.strptime(raw.strip(), "%m/%d/%Y").date()


########################################################################
########################################################################
#
def parse(source: str | Path) -> Iterator[ParsedTransaction]:
    """
    Parse a Bank of America CSV export file.

    Skips the summary section, the header row, and the "Beginning balance"
    row. Yields one ParsedTransaction per settled transaction.

    Args:
        source: File path (str or Path) to the BofA CSV export.

    Yields:
        ParsedTransaction for each transaction row in the file.

    Raises:
        ValueError: If the transaction section header is not found.
        FileNotFoundError: If the file does not exist.
    """
    path = Path(source)
    raw_text = path.read_text(encoding="utf-8-sig")  # strip BOM if present

    # Split into summary section and transaction section at the blank line.
    #
    parts = raw_text.split("\n\n", maxsplit=1)
    if len(parts) < 2:
        # Try Windows-style line endings.
        parts = raw_text.split("\r\n\r\n", maxsplit=1)
    if len(parts) < 2:
        raise ValueError(
            "Could not find the blank line separating summary from "
            "transactions in the BofA CSV file."
        )

    transaction_section = parts[1].strip()
    reader = csv.DictReader(transaction_section.splitlines())

    # Validate expected columns.
    expected = {"Date", "Description", "Amount", "Running Bal."}
    if reader.fieldnames is None or not expected.issubset(
        set(reader.fieldnames)
    ):
        raise ValueError(
            f"Unexpected columns in BofA CSV transaction section. "
            f"Expected {expected}, got {reader.fieldnames!r}."
        )

    for row in reader:
        # Skip the "Beginning balance" row -- it has no Amount.
        if not row["Amount"].strip():
            continue

        transaction_date = _parse_date(row["Date"])
        raw_description = row["Description"].strip()
        amount = _parse_amount(row["Amount"])
        running_balance = _parse_amount(row["Running Bal."])
        transaction_type = _infer_transaction_type(raw_description)

        yield ParsedTransaction(
            transaction_date=transaction_date,
            raw_description=raw_description,
            amount=amount,
            running_balance=running_balance,
            transaction_type=transaction_type,
        )
