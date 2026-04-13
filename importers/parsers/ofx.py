"""
OFX / QFX statement parser.

OFX (Open Financial Exchange) is an SGML/XML format for exchanging
financial data; QFX is Intuit's branded variant of the same format
with a proprietary ``<INTU.*>`` block that the underlying ``ofxparse``
library handles transparently. One parser serves both -- the importer
dispatches to this module on either ``.ofx`` or ``.qfx`` extensions.

Unlike the BofA CSV format, OFX carries structured account identity
(``<ACCTID>``), structured account type (``<ACCTTYPE>`` for bank
accounts, or the ``<CCSTMTRS>`` section for credit cards), and a
structured transaction type enum (``<TRNTYPE>``). Transaction type
inference is therefore a simple mapping table rather than the regex
heuristic the BofA CSV parser has to resort to.

OFX statements report the ledger balance at the end of the statement
window (``<LEDGERBAL><BALAMT>``) but typically do NOT report an
opening balance. This parser derives ``beginning_balance`` by
subtracting the summed transaction amounts from ``ending_balance``
and walks ``running_balance`` forward from there so the downstream
``validate_statement`` walk continues to work without special-casing
OFX.
"""

# system imports
import logging
from datetime import date
from decimal import Decimal
from pathlib import Path

# 3rd party imports
import ofxparse

# Project imports
from importers.parsers.common import ParsedStatement, ParsedTransaction

logger = logging.getLogger(__name__)

__all__ = ["parse", "validate_statement"]


# OFX TRNTYPE values (as lowercased by ofxparse) to mibudge
# Transaction.TransactionType codes. TRNTYPE values that are
# ambiguous on their own (generic "debit"/"credit") are deliberately
# absent -- they fall through to a sign-based default in
# ``_infer_transaction_type``.
#
# OFX 2.x SEC-1 enumerates: CREDIT, DEBIT, INT, DIV, FEE, SRVCHG, DEP,
# ATM, POS, XFER, CHECK, PAYMENT, CASH, DIRECTDEP, DIRECTDEBIT,
# REPEATPMT, HOLD, OTHER. ofxparse lowercases these and rewrites
# ``directdep`` -> ``dir_deposit`` and ``directdebit`` ->
# ``direct_debit``.
#
_OFX_TYPE_MAP: dict[str, str] = {
    "int": "interest_credit",
    "fee": "fee",
    "srvchg": "fee",
    "atm": "atm_withdrawal",
    "pos": "signature_purchase",
    "xfer": "shared_transfer",
    "check": "check",
    "payment": "bill_payment",
    "cash": "atm_withdrawal",
    "dep": "check_deposit",
    "directdep": "ach",
    "dir_deposit": "ach",
    "directdebit": "ach",
    "direct_debit": "ach",
    "repeatpmt": "bill_payment",
}


# OFX account_type strings (ofxparse lowercases the ACCTTYPE content
# for bank accounts) to mibudge BankAccount.BankAccountType codes.
# Credit-card statements come through in the CREDITCARDMSGSRSV1
# section and have AccountType.CreditCard at the Account level; we
# handle that separately in ``_resolve_account_type``.
#
_OFX_BANK_ACCOUNT_TYPE_MAP: dict[str, str] = {
    "checking": "C",
    "savings": "S",
    # Other OFX bank types (moneymrkt, creditline, cd) are rare in
    # consumer statements; leave them unmapped so the importer asks
    # for an explicit --account-type rather than guessing.
}


####################################################################
#
def _infer_transaction_type(trntype: str | None, amount: Decimal) -> str:
    """
    Map an OFX TRNTYPE string to a mibudge TransactionType code.

    The OFX spec defines TRNTYPE as a closed enum, so most of the work
    is a table lookup. The two generic values ("credit" and "debit")
    carry no semantic information beyond the sign of the amount; for
    those (and for missing TRNTYPE) we fall back to the same rule the
    BofA CSV parser uses -- positive amounts default to
    ``bank_generated_credit``, negative debits default to
    ``signature_purchase``.

    Args:
        trntype: TRNTYPE string from the OFX transaction (already
            lowercased by ofxparse), or ``None`` if the transaction
            had no TRNTYPE tag.
        amount:  Signed transaction amount.

    Returns:
        A ``Transaction.TransactionType`` code string, or ``""``
        (NOT_SET) if the sign of the amount doesn't give us anything
        actionable either.
    """
    if trntype:
        mapped = _OFX_TYPE_MAP.get(trntype)
        if mapped is not None:
            return mapped

    # Fall through for generic "debit"/"credit", "other", or missing
    # TRNTYPE. Use the sign of the amount as the last-resort signal.
    if amount > 0:
        return "bank_generated_credit"
    if amount < 0:
        return "signature_purchase"
    return ""


####################################################################
#
def _resolve_account_type(account: ofxparse.Account) -> str | None:
    """
    Return the mibudge BankAccount.BankAccountType code for an OFX account.

    Args:
        account: The ``ofxparse.Account`` for the statement.

    Returns:
        "C" (checking), "S" (savings), or "X" (credit card) when the
        OFX file identifies the type unambiguously; ``None`` when the
        statement is of an unsupported type (investments, money market,
        credit line, etc.) so the importer can either ask the user or
        refuse the create path.
    """
    if account.type == ofxparse.AccountType.CreditCard:
        return "X"
    if account.type == ofxparse.AccountType.Bank:
        # ACCTTYPE is in account.account_type, lowercased by ofxparse.
        return _OFX_BANK_ACCOUNT_TYPE_MAP.get(
            (account.account_type or "").lower()
        )
    return None


####################################################################
#
def _compose_description(txn: ofxparse.Transaction) -> str:
    """
    Build a human-readable description from an OFX transaction.

    OFX transactions carry ``NAME`` (the payee, <= 32 chars per spec)
    and ``MEMO`` (free-form). The two are often both present and
    complementary ("APPLECARD" + "Payment to Apple Card") so we
    concatenate when both are non-empty. Check transactions also carry
    a ``<CHECKNUM>`` which goes on the front so description-based
    parsers downstream can pick up "Check 318" style strings.

    Args:
        txn: The ``ofxparse.Transaction``.

    Returns:
        A single-line description string (never empty if the
        transaction had any identifying text).
    """
    parts: list[str] = []
    checknum = (txn.checknum or "").strip()
    if checknum:
        parts.append(f"Check {checknum}")
    payee = (txn.payee or "").strip()
    memo = (txn.memo or "").strip()
    if payee and memo and payee != memo:
        parts.append(f"{payee} -- {memo}")
    elif payee:
        parts.append(payee)
    elif memo:
        parts.append(memo)
    return " ".join(parts) if parts else "(no description)"


########################################################################
########################################################################
#
def parse(source: str | Path) -> ParsedStatement:
    """
    Parse an OFX or QFX statement file.

    OFX only reports the ledger balance at statement end, not the
    opening balance. ``beginning_balance`` is therefore derived as
    ``ending_balance - sum(transaction amounts)`` and
    ``running_balance`` is walked forward from that value so the
    downstream ``validate_statement`` running-balance walk works
    uniformly across formats. In practice this never catches a real
    bug in an OFX file (the math is tautological by construction) but
    the uniform shape is worth more than the redundant check.

    Args:
        source: Path (str or Path) to the OFX/QFX file.

    Returns:
        A populated ``ParsedStatement``. ``acct_id`` is the OFX
        ``ACCTID`` (account identifier reported by the FI).
        ``account_type`` is the mibudge type code ("C"/"S"/"X") when
        the statement identifies the account type unambiguously,
        otherwise ``None``.

    Raises:
        ValueError: If the file is not a recognisable OFX statement
            (no account or statement found).
        FileNotFoundError: If the file does not exist.
    """
    path = Path(source)
    with path.open("rb") as fh:
        # fail_fast=False so one malformed transaction doesn't abort
        # the whole file; ofxparse still records the bad row for us
        # in ``statement.discarded_entries`` if we ever want to surface
        # it.
        ofx = ofxparse.OfxParser.parse(fh, fail_fast=False)

    account = ofx.account
    if account is None or account.statement is None:
        raise ValueError(
            f"OFX file {path} contains no account/statement section."
        )

    statement = account.statement
    account_type_code = _resolve_account_type(account)

    # Build transactions in source order, walking running balance
    # forward. OFX does not report a running balance per transaction,
    # so we derive one.
    tx_sum = sum(
        (Decimal(str(t.amount)) for t in statement.transactions), Decimal("0")
    )
    ending_balance = Decimal(str(statement.balance))
    beginning_balance = (ending_balance - tx_sum).quantize(Decimal("0.01"))

    running = beginning_balance
    total_credits = Decimal("0")
    total_debits = Decimal("0")
    parsed_txs: list[ParsedTransaction] = []
    for t in statement.transactions:
        amount = Decimal(str(t.amount)).quantize(Decimal("0.01"))
        running = (running + amount).quantize(Decimal("0.01"))
        if amount > 0:
            total_credits += amount
        else:
            total_debits += amount

        tx_date: date = t.date.date() if hasattr(t.date, "date") else t.date
        trntype = (t.type or "").lower() or None
        transaction_type = _infer_transaction_type(trntype, amount)

        parsed_txs.append(
            ParsedTransaction(
                transaction_date=tx_date,
                raw_description=_compose_description(t),
                amount=amount,
                running_balance=running,
                transaction_type=transaction_type,
            )
        )

    beginning_date: date = (
        statement.start_date.date()
        if hasattr(statement.start_date, "date")
        else statement.start_date
    )
    ending_date: date = (
        statement.end_date.date()
        if hasattr(statement.end_date, "date")
        else statement.end_date
    )

    return ParsedStatement(
        beginning_balance=beginning_balance,
        beginning_date=beginning_date,
        ending_balance=ending_balance.quantize(Decimal("0.01")),
        ending_date=ending_date,
        total_credits=total_credits.quantize(Decimal("0.01")),
        total_debits=total_debits.quantize(Decimal("0.01")),
        transactions=parsed_txs,
        acct_id=(account.number or None),
        account_type=account_type_code,
        source_path=str(path),
        # OFX only reports LEDGERBAL, which some FIs (Apple, at least)
        # populate with the balance at download time rather than the
        # statement-end balance. When that happens the per-file
        # derived ``beginning_balance`` above is wrong and the
        # combiner must recompute it from the walk across all files.
        beginning_balance_reported=False,
    )


########################################################################
########################################################################
#
def validate_statement(statement: ParsedStatement) -> list[str]:
    """
    Verify a parsed OFX statement is internally consistent.

    The check is the same running-balance walk used for BofA CSVs.
    Because OFX beginning balances are derived rather than reported,
    a mismatch here would indicate a numeric parsing bug in this
    module, not a corrupt file -- but keeping the check in place
    gives the import pipeline a uniform shape.

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
                f"{tx.raw_description[:40]!r}): running balance mismatch "
                f"-- computed {running}, statement says {tx.running_balance}."
            )
            break
    return errors
