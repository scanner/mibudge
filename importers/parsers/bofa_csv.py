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
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

# Project imports
from importers.parsers.common import ParsedStatement, ParsedTransaction

logger = logging.getLogger(__name__)

__all__ = [
    "ParsedStatement",
    "ParsedTransaction",
    "parse",
    "validate_statement",
]


########################################################################
########################################################################
#
# Keyword patterns for transaction type inference from BofA descriptions.
# Checked in order; first match wins.
#
# NOTE: Regex matching on the free-form description is a hacky approach
# -- BofA's description strings are not a stable API, and collisions
# between patterns (e.g. a merchant name that happens to contain
# "REFUND") are always possible. It is good enough for the volume and
# variety of data we actually see, and the import script logs every
# unclassified description so we can extend the pattern list and
# re-run the import to backfill. If we ever ingest from a source with
# structured transaction-type codes (OFX/QFX TRNTYPE, for example),
# prefer those over this list.
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
    # Refunds from merchants (e.g. "TST*MERCHANT 10/26 REFUND ..." or
    # "AMAZON MKTPLACE PMTS 04/14 REFUND Amzn.com/bill WA"). Must come
    # before the PURCHASE pattern because some refund rows also contain
    # "PURCHASE".
    (re.compile(r"\bREFUND\b", re.IGNORECASE), "signature_credit"),
    # BofA online bill pay (e.g. "Comcast Cable Communications Bill
    # Payment", "AT&T Mobility (Cingular) Bill Payment").
    (re.compile(r"\bBill\s+Payment\b", re.IGNORECASE), "bill_payment"),
    # BofA foreign currency order (e.g. "FX Order Confirmation# XXXXX62185").
    (re.compile(r"\bFX\s+Order\b", re.IGNORECASE), "fx_order"),
    (
        re.compile(r"\b(MOBILE\s+)?PURCHASE\b", re.IGNORECASE),
        "signature_purchase",
    ),
    (re.compile(r"\bPAYROLL\b", re.IGNORECASE), "ach"),
    (re.compile(r"\bDIRECT\s+DEP(OSIT)?\b", re.IGNORECASE), "ach"),
    (re.compile(r"\bWIRE\b", re.IGNORECASE), "wire_transfer"),
    (re.compile(r"\bCHECK\s+DEPOSIT\b", re.IGNORECASE), "check_deposit"),
    # Paper check written against the account (e.g. "Check 318").
    # Must come after CHECK DEPOSIT so mobile deposits don't match first.
    (re.compile(r"\bCheck\s+\d+\b", re.IGNORECASE), "check"),
    # Class-action settlement credit paid by the bank (descriptions
    # contain a case caption followed by "Class Settlement").
    (
        re.compile(r"\bClass\s+Settlement\b", re.IGNORECASE),
        "bank_generated_credit",
    ),
    (re.compile(r"\bINTEREST\b", re.IGNORECASE), "interest_credit"),
    (re.compile(r"\bSERVICE\s+CHARGE\b|\bFEE\b", re.IGNORECASE), "fee"),
    # ACH transactions -- DES: format is used for structured ACH entries.
    # Standard Entry Class codes (PPD, CCD, WEB, etc.) follow at end.
    (re.compile(r"\bDES:", re.IGNORECASE), "ach"),
    (re.compile(r"\b(PPD|CCD|WEB|TEL|ARC|RCK)\b"), "ach"),
]


####################################################################
#
def _infer_transaction_type(description: str, amount: Decimal) -> str:
    """
    Infer a TransactionType value from a BofA transaction description.

    NOTE: This is a hacky keyword-match approach -- see the comment on
    ``_TYPE_PATTERNS`` above. It works well enough for the BofA CSV
    export format but is not a substitute for a source with structured
    type codes. Unmatched descriptions are logged so patterns can be
    extended iteratively.

    If no pattern matches but the amount is a credit (positive), fall
    back to ``bank_generated_credit``. One-off credits (settlements,
    promotional credits, adjustments) are rare and highly varied in
    wording -- chasing every new phrasing with a bespoke regex is not
    worth the effort when a single catch-all is a reasonable default.

    Args:
        description: Raw description string from the CSV.
        amount:      Signed decimal amount; positive = credit, negative = debit.

    Returns:
        A TransactionType value string, or "" (NOT_SET) if no pattern
        matches and the amount is a debit.
    """
    for pattern, transaction_type in _TYPE_PATTERNS:
        if pattern.search(description):
            return transaction_type
    if amount > 0:
        logger.info(
            "Unrecognized credit description, defaulting to "
            "bank_generated_credit: %r",
            description,
        )
        return "bank_generated_credit"
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


####################################################################
#
_BEGINNING_RE = re.compile(r"Beginning balance as of (\d{2}/\d{2}/\d{4})")
_ENDING_RE = re.compile(r"Ending balance as of (\d{2}/\d{2}/\d{4})")


def _parse_summary_section(
    section: str,
) -> dict[str, Decimal | date]:
    """
    Parse the summary block at the top of a BofA CSV.

    The summary has four rows after the header:

        Beginning balance as of MM/DD/YYYY,,"N,NNN.NN"
        Total credits,,"N,NNN.NN"
        Total debits,,"-N,NNN.NN"
        Ending balance as of MM/DD/YYYY,,"N,NNN.NN"

    The function is tolerant of absent rows: fields default to
    ``Decimal("0")`` / ``None`` so callers get a clear error when
    something expected is missing.

    Args:
        section: The raw text of the summary section (before the blank
            line separator).

    Returns:
        A dict with keys ``beginning_balance``, ``beginning_date``,
        ``ending_balance``, ``ending_date``, ``total_credits``,
        ``total_debits``.

    Raises:
        ValueError: If the beginning or ending balance rows cannot be
            located (without them we cannot validate or seed balances).
    """
    reader = csv.reader(section.splitlines())
    rows = [r for r in reader if any(c.strip() for c in r)]

    out: dict[str, Decimal | date] = {
        "total_credits": Decimal("0"),
        "total_debits": Decimal("0"),
    }

    for row in rows:
        if len(row) < 3:
            continue
        label, _, amount_str = row[0].strip(), row[1], row[2].strip()
        if not amount_str:
            continue

        m_begin = _BEGINNING_RE.match(label)
        m_end = _ENDING_RE.match(label)
        if m_begin:
            out["beginning_balance"] = _parse_amount(amount_str)
            out["beginning_date"] = _parse_date(m_begin.group(1))
        elif m_end:
            out["ending_balance"] = _parse_amount(amount_str)
            out["ending_date"] = _parse_date(m_end.group(1))
        elif label.lower() == "total credits":
            out["total_credits"] = _parse_amount(amount_str)
        elif label.lower() == "total debits":
            out["total_debits"] = _parse_amount(amount_str)

    missing = {"beginning_balance", "ending_balance"} - out.keys()
    if missing:
        raise ValueError(
            f"BofA CSV summary is missing required row(s): {sorted(missing)}."
        )
    return out


########################################################################
########################################################################
#
def parse(source: str | Path) -> ParsedStatement:
    """
    Parse a Bank of America CSV export file.

    Returns a ``ParsedStatement`` containing the summary metadata
    (beginning/ending balance and dates, credit/debit totals) and the
    list of parsed transactions in file order.

    Args:
        source: File path (str or Path) to the BofA CSV export.

    Returns:
        A populated ``ParsedStatement``.

    Raises:
        ValueError: If the file layout is unexpected (missing section
            separator, unknown columns, missing summary rows).
        FileNotFoundError: If the file does not exist.
    """
    path = Path(source)
    raw_text = path.read_text(encoding="utf-8-sig")  # strip BOM if present

    # Split into summary section and transaction section at the blank line.
    parts = raw_text.split("\n\n", maxsplit=1)
    if len(parts) < 2:
        # Try Windows-style line endings.
        parts = raw_text.split("\r\n\r\n", maxsplit=1)
    if len(parts) < 2:
        raise ValueError(
            "Could not find the blank line separating summary from "
            "transactions in the BofA CSV file."
        )

    summary = _parse_summary_section(parts[0])

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

    transactions: list[ParsedTransaction] = []
    for row in reader:
        # Skip the "Beginning balance" row -- it has no Amount.
        if not row["Amount"].strip():
            continue

        transaction_date = _parse_date(row["Date"])
        raw_description = row["Description"].strip()
        amount = _parse_amount(row["Amount"])
        running_balance = _parse_amount(row["Running Bal."])
        transaction_type = _infer_transaction_type(raw_description, amount)

        transactions.append(
            ParsedTransaction(
                transaction_date=transaction_date,
                raw_description=raw_description,
                amount=amount,
                running_balance=running_balance,
                transaction_type=transaction_type,
            )
        )

    return ParsedStatement(
        beginning_balance=summary["beginning_balance"],  # type: ignore[arg-type]
        beginning_date=summary["beginning_date"],  # type: ignore[arg-type]
        ending_balance=summary["ending_balance"],  # type: ignore[arg-type]
        ending_date=summary["ending_date"],  # type: ignore[arg-type]
        total_credits=summary["total_credits"],  # type: ignore[arg-type]
        total_debits=summary["total_debits"],  # type: ignore[arg-type]
        transactions=transactions,
        source_path=str(path),
    )


########################################################################
########################################################################
#
def validate_statement(statement: ParsedStatement) -> list[str]:
    """
    Verify a parsed BofA statement is internally consistent.

    Runs two checks:

    1. **Running balance walk.** Walking transactions in file order
       from *beginning_balance*, after applying each transaction's
       signed amount, the cumulative balance must match that row's
       own ``running_balance``. A mismatch means either a parsing
       error or a corrupt CSV and the import should not proceed.

    2. **Summary totals.** ``beginning_balance + total_credits +
       total_debits == ending_balance``. BofA reports ``total_debits``
       as a negative number, so the formula uses addition. A mismatch
       here means the summary block is inconsistent with the detail
       rows.

    Args:
        statement: A ``ParsedStatement`` returned by ``parse()``.

    Returns:
        A list of human-readable error messages. Empty if everything
        balances.
    """
    errors: list[str] = []

    running = statement.beginning_balance
    for idx, tx in enumerate(statement.transactions, start=1):
        running = (running + tx.amount).quantize(Decimal("0.01"))
        if running != tx.running_balance.quantize(Decimal("0.01")):
            errors.append(
                f"Row {idx} ({tx.transaction_date} {tx.amount} "
                f"{tx.raw_description[:40]!r}): running balance "
                f"mismatch -- computed {running}, CSV says "
                f"{tx.running_balance}."
            )
            # One mismatch cascades; report only the first.
            break

    expected_ending = (
        statement.beginning_balance
        + statement.total_credits
        + statement.total_debits
    ).quantize(Decimal("0.01"))
    actual_ending = statement.ending_balance.quantize(Decimal("0.01"))
    if expected_ending != actual_ending:
        errors.append(
            f"Summary totals mismatch: beginning ({statement.beginning_balance}) "
            f"+ credits ({statement.total_credits}) + debits "
            f"({statement.total_debits}) = {expected_ending}, but CSV "
            f"ending balance is {actual_ending}."
        )

    return errors
