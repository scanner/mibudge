"""
Shared dataclasses for bank-statement parsers.

Each concrete parser (BofA CSV, OFX, etc.) turns **one raw file** into
**one** ``ParsedStatement`` containing that file's summary metadata and
a list of ``ParsedTransaction`` records. Multi-file imports run one
parser call per file and combine the resulting ``ParsedStatement``
objects at the importer level. The importer consumes the dataclasses
without caring which parser produced them.

Format-specific parsers live alongside this module; the dispatcher in
``importers.import_transactions`` picks one based on file extension.
"""

# system imports
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


########################################################################
########################################################################
#
@dataclass
class ParsedTransaction:
    """
    A single transaction extracted from a bank statement.

    Args:
        transaction_date: Settlement or posted date.
        raw_description:  Description string from the source file. For
            OFX this is assembled from NAME/PAYEE and MEMO.
        amount:           Signed decimal amount. Negative = debit, positive = credit.
        running_balance:  Account running balance after this transaction.
            For formats that don't record this (OFX), the parser computes
            it by walking forward from the derived beginning balance.
        transaction_type: One of ``Transaction.TransactionType`` values, or
            "" (NOT_SET) if the source couldn't disambiguate.
        pending:          True if the source marks the transaction as pending.
            Most statement exports contain only settled transactions.
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
@dataclass
class ParsedStatement:
    """
    One statement worth of transactions + summary metadata.

    A ``ParsedStatement`` corresponds to a single source file: one file
    in, one ``ParsedStatement`` out. When the importer is invoked with
    multiple files (e.g. ``import *.ofx``) it produces one
    ``ParsedStatement`` per file, sorts them by ``beginning_date``, and
    then feeds their combined transactions through the shared dedup +
    POST pipeline.

    Note on terminology: for BofA CSV exports a single file may span
    several monthly statement cycles, so "statement" is slightly loose
    -- the invariant the parser enforces is really "everything in this
    one file," not "a single monthly statement period."

    Args:
        beginning_balance: Balance at ``beginning_date``. For OFX (which
            only reports the ending ledger balance) this is computed by
            subtracting the summed transactions from the ending balance.
        beginning_date:    First date covered by the statement.
        ending_balance:    Balance at ``ending_date``.
        ending_date:       Last date covered by the statement.
        total_credits:     Sum of credit amounts (positive).
        total_debits:      Sum of debit amounts (negative).
        transactions:      Transactions in source order.
        acct_id:           Statement-carried account identifier (OFX
            ``ACCTID``), or None for formats that don't expose one. Used
            by the importer to match against an existing BankAccount's
            ``account_number`` and to sanity-check that files combined
            in one run belong to the same account.
        account_type:      Model choice code ("C"/"S"/"X") derived from
            the statement itself, or None if the source doesn't carry
            the information. When set, ``--create-account`` uses this
            instead of accepting an ``--account-type`` flag.
        source_path:       Filesystem path the statement was parsed
            from; used for diagnostic messages when multiple statements
            are combined in one import run.
        beginning_balance_reported: True when the source file itself
            reports the beginning balance as a separate field (BofA
            CSV summary block). False when it is derived by the parser
            from the ending balance and the transaction sum (OFX/QFX,
            whose LEDGERBAL can be the balance at download time rather
            than the statement-end balance -- when that is the case,
            the derived per-file beginning is not trustworthy and
            ``_combine_statements`` recomputes it from the walk).
    """

    beginning_balance: Decimal
    beginning_date: date
    ending_balance: Decimal
    ending_date: date
    total_credits: Decimal
    total_debits: Decimal
    transactions: list[ParsedTransaction] = field(default_factory=list)
    acct_id: str | None = None
    account_type: str | None = None
    source_path: str | None = None
    beginning_balance_reported: bool = True
