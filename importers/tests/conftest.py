"""
Fixtures for importer tests.

Per-row factories (``BofaCSVRowFactory``, ``OFXTxnSpecFactory``) live in
``factories.py`` and are registered here via
``pytest_factoryboy.register()`` -- each becomes a snake_case callable
fixture (``bofa_csv_row_factory``, ``ofx_txn_spec_factory``).

The file-writing fixtures ``bofa_csv_factory`` and ``ofx_file_factory``
sit on top of those per-row factories: they handle the statement-level
concerns (walking running balances, synthesizing opening/closing dates,
serializing to the on-disk format) that factory_boy is not the right
tool for.

``client`` + ``mock_auth`` are test-client fixtures, unrelated to file
generation.
"""

# system imports
import csv
import io
import json
import os
from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

# 3rd party imports
import httpx
import pytest
from pytest_factoryboy import register
from pytest_mock import MockerFixture

# Project imports
from importers.client import MibudgeClient
from importers.tests.factories import (
    BofaCSVRow,
    BofaCSVRowFactory,
    OFXTxnSpec,
    OFXTxnSpecFactory,
)

register(BofaCSVRowFactory)  # -> bofa_csv_row_factory fixture
register(OFXTxnSpecFactory)  # -> ofx_txn_spec_factory fixture


####################################################################
#
def _fmt_amount(value: Decimal) -> str:
    """Format a Decimal as a BofA amount string (comma thousands, 2dp)."""
    quantized = value.quantize(Decimal("0.01"))
    abs_val = abs(quantized)
    formatted = f"{abs_val:,.2f}"
    return f"-{formatted}" if quantized < 0 else formatted


####################################################################
#
def _write_bofa_csv(
    path: Path,
    rows: list[BofaCSVRow],
    beginning_balance: Decimal,
    beginning_date: date,
    ending_date: date,
) -> None:
    """
    Write a BofA-format CSV file to *path*.

    Derives Total credits, Total debits, and Ending balance from the
    provided rows and beginning balance.
    """
    total_credits = sum((r.amount for r in rows if r.amount > 0), Decimal("0"))
    total_debits = sum((r.amount for r in rows if r.amount < 0), Decimal("0"))
    ending_balance = rows[-1].running_balance if rows else beginning_balance

    buf = io.StringIO()
    w = csv.writer(buf)

    w.writerow(["Description", "", "Summary Amt."])
    w.writerow(
        [
            f"Beginning balance as of {beginning_date:%m/%d/%Y}",
            "",
            _fmt_amount(beginning_balance),
        ]
    )
    w.writerow(["Total credits", "", _fmt_amount(total_credits)])
    w.writerow(["Total debits", "", _fmt_amount(total_debits)])
    w.writerow(
        [
            f"Ending balance as of {ending_date:%m/%d/%Y}",
            "",
            _fmt_amount(ending_balance),
        ]
    )

    buf.write("\n")

    w.writerow(["Date", "Description", "Amount", "Running Bal."])
    w.writerow(
        [
            f"{beginning_date:%m/%d/%Y}",
            f"Beginning balance as of {beginning_date:%m/%d/%Y}",
            "",
            _fmt_amount(beginning_balance),
        ]
    )
    for row in rows:
        w.writerow(
            [
                f"{row.transaction_date:%m/%d/%Y}",
                row.description,
                _fmt_amount(row.amount),
                _fmt_amount(row.running_balance),
            ]
        )

    path.write_text(buf.getvalue(), encoding="utf-8")


########################################################################
########################################################################
#
@pytest.fixture
def bofa_csv_factory(
    bofa_csv_row_factory: Callable[..., BofaCSVRow],
    tmp_path: Path,
) -> Callable[..., tuple[Path, list[BofaCSVRow]]]:
    """
    Return a factory that generates a BofA-format CSV file on disk.

    The factory delegates per-row generation to ``bofa_csv_row_factory``
    (built from ``BofaCSVRowFactory``) and layers the statement-level
    balance-walk on top: running balances are recomputed so the file
    validates cleanly against ``validate_statement``.

    Signature::

        bofa_csv_factory(
            num_transactions: int = 10,
            beginning_balance: Decimal | float | str = "1000.00",
            start_date: date | None = None,   # default: 90 days ago
            end_date: date | None = None,     # default: today
        ) -> tuple[Path, list[BofaCSVRow]]

    Amounts come from the row factory's Faker defaults (small debits
    in the -$200..-$1 range). To keep balances positive for larger
    transaction counts we occasionally insert a credit by overriding
    ``amount`` on the factory call; the running-balance walk happens
    after that so the file always validates.
    """

    def _factory(
        num_transactions: int = 10,
        beginning_balance: Decimal | float | str = "1000.00",
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> tuple[Path, list[BofaCSVRow]]:
        today = date.today()
        start = start_date or (today - timedelta(days=90))
        end = end_date or today
        balance = Decimal(str(beginning_balance)).quantize(Decimal("0.01"))

        date_range = (end - start).days or 1
        step = max(date_range // max(num_transactions, 1), 1)

        rows: list[BofaCSVRow] = []
        for i in range(num_transactions):
            tx_date = start + timedelta(days=i * step)
            if tx_date > end:
                tx_date = end

            # Every third row, inject a credit so the balance doesn't
            # drift negative with many debits. Let the factory generate
            # everything else.
            if i % 3 == 2:
                row = bofa_csv_row_factory(
                    transaction_date=tx_date,
                    amount=Decimal("150.00"),
                )
            else:
                row = bofa_csv_row_factory(transaction_date=tx_date)

            balance = (balance + row.amount).quantize(Decimal("0.01"))
            # Per-row factories default ``running_balance`` to 0; fill
            # it in now that we know the statement-level walk.
            row.running_balance = balance
            rows.append(row)

        csv_path = tmp_path / "bofa_sample.csv"
        _write_bofa_csv(
            path=csv_path,
            rows=rows,
            beginning_balance=Decimal(str(beginning_balance)).quantize(
                Decimal("0.01")
            ),
            beginning_date=start,
            ending_date=end,
        )
        return csv_path, rows

    return _factory


####################################################################
#
def _ofx_datetime(d: date) -> str:
    """Format a date as the OFX DTPOSTED YYYYMMDDHHMMSS form."""
    return datetime.combine(d, datetime.min.time()).strftime("%Y%m%d%H%M%S")


####################################################################
#
def _write_ofx_file(
    path: Path,
    specs: list[OFXTxnSpec],
    acct_id: str,
    bank_id: str,
    account_type: str,  # "CHECKING" / "SAVINGS"
    ending_balance: Decimal,
    start_date: date,
    end_date: date,
) -> None:
    """
    Serialize a list of transaction specs into an SGML-form OFX file.

    This is the compact (non-XML) OFX 1.x form that ``ofxparse``
    accepts cleanly. Indentation is cosmetic; OFX parsers treat the
    body as whitespace-insensitive SGML.
    """
    tx_blocks: list[str] = []
    for spec in specs:
        block = [
            "<STMTTRN>",
            f"<TRNTYPE>{spec.trntype}",
            f"<DTPOSTED>{_ofx_datetime(spec.transaction_date)}",
            f"<TRNAMT>{spec.amount:.2f}",
            f"<FITID>{spec.fitid}",
        ]
        if spec.checknum:
            block.append(f"<CHECKNUM>{spec.checknum}")
        block.append(f"<NAME>{spec.name}")
        if spec.memo:
            block.append(f"<MEMO>{spec.memo}")
        block.append("</STMTTRN>")
        tx_blocks.append("\n".join(block))

    body = f"""OFXHEADER:100
DATA:OFXSGML
VERSION:102
SECURITY:NONE
ENCODING:USASCII
CHARSET:1252
COMPRESSION:NONE
OLDFILEUID:NONE
NEWFILEUID:NONE

<OFX>
<SIGNONMSGSRSV1>
<SONRS>
<STATUS><CODE>0<SEVERITY>INFO</STATUS>
<DTSERVER>{_ofx_datetime(end_date)}
<LANGUAGE>ENG
</SONRS>
</SIGNONMSGSRSV1>
<BANKMSGSRSV1>
<STMTTRNRS>
<TRNUID>1
<STATUS><CODE>0<SEVERITY>INFO</STATUS>
<STMTRS>
<CURDEF>USD
<BANKACCTFROM>
<BANKID>{bank_id}
<ACCTID>{acct_id}
<ACCTTYPE>{account_type}
</BANKACCTFROM>
<BANKTRANLIST>
<DTSTART>{_ofx_datetime(start_date)}
<DTEND>{_ofx_datetime(end_date)}
{chr(10).join(tx_blocks)}
</BANKTRANLIST>
<LEDGERBAL>
<BALAMT>{ending_balance:.2f}
<DTASOF>{_ofx_datetime(end_date)}
</LEDGERBAL>
</STMTRS>
</STMTTRNRS>
</BANKMSGSRSV1>
</OFX>
"""
    path.write_text(body, encoding="utf-8")


########################################################################
########################################################################
#
@pytest.fixture
def ofx_file_factory(
    ofx_txn_spec_factory: Callable[..., OFXTxnSpec],
    tmp_path: Path,
) -> Callable[..., tuple[Path, list[OFXTxnSpec]]]:
    """
    Return a factory that generates an OFX file on disk.

    Signature::

        ofx_file_factory(
            specs: list[OFXTxnSpec] | None = None,
            num_transactions: int = 5,
            acct_id: str = "1234567890",
            bank_id: str = "121000358",
            account_type: str = "CHECKING",    # or "SAVINGS"
            ending_balance: Decimal | str = "1000.00",
            start_date: date | None = None,    # default: 30 days ago
            end_date: date | None = None,      # default: today
            filename: str = "sample.ofx",
        ) -> tuple[Path, list[OFXTxnSpec]]

    When ``specs`` is None the factory builds ``num_transactions`` specs
    from ``OFXTxnSpecFactory`` defaults. Callers wanting targeted
    scenarios (a CHECK row, an INT credit, etc.) pass pre-built specs
    via the ``ofx_txn_spec_factory`` fixture.
    """

    def _factory(
        specs: list[OFXTxnSpec] | None = None,
        num_transactions: int = 5,
        acct_id: str = "1234567890",
        bank_id: str = "121000358",
        account_type: str = "CHECKING",
        ending_balance: Decimal | str = "1000.00",
        start_date: date | None = None,
        end_date: date | None = None,
        filename: str = "sample.ofx",
    ) -> tuple[Path, list[OFXTxnSpec]]:
        today = date.today()
        start = start_date or (today - timedelta(days=30))
        end = end_date or today

        if specs is None:
            specs = [
                ofx_txn_spec_factory(
                    transaction_date=start
                    + timedelta(
                        days=(i * max((end - start).days, 1))
                        // max(num_transactions, 1)
                    )
                )
                for i in range(num_transactions)
            ]

        ofx_path = tmp_path / filename
        _write_ofx_file(
            path=ofx_path,
            specs=specs,
            acct_id=acct_id,
            bank_id=bank_id,
            account_type=account_type,
            ending_balance=Decimal(str(ending_balance)).quantize(
                Decimal("0.01")
            ),
            start_date=start,
            end_date=end,
        )
        return ofx_path, specs

    return _factory


########################################################################
########################################################################
#
@pytest.fixture
def client(mocker: MockerFixture) -> MibudgeClient:
    """Return a MibudgeClient pre-configured to talk to the test server.

    SSL_CERT_FILE is removed so that a developer's local .env pointing at a
    machine-specific cert file does not cause httpx to fail when creating its
    SSL context for the plain-HTTP test server URL.
    """
    env = {k: v for k, v in os.environ.items() if k != "SSL_CERT_FILE"}
    mocker.patch.dict(os.environ, env, clear=True)
    return MibudgeClient("http://testserver", "user", "pass")


########################################################################
########################################################################
#
@pytest.fixture
def mock_auth(mocker: MockerFixture) -> Callable[..., MagicMock]:
    """
    Return a factory that patches a client's token endpoint.

    The factory signature is::

        mock_auth(
            client: MibudgeClient,
            *,
            access: str = "token-abc",
            status: int = 200,
        ) -> MagicMock

    Patches ``client._http.post`` so that ``POST /api/token/`` returns a
    response with the given status code.  On 200 the body contains
    ``{"access": access, "refresh": "r"}``; on any other status it
    contains a generic error detail.

    Returns the MagicMock so tests can assert on call counts/args if
    needed.
    """

    def _patch(
        client: MibudgeClient,
        *,
        access: str = "token-abc",
        status: int = 200,
    ) -> MagicMock:
        body = (
            {"access": access, "refresh": "r"}
            if status == 200
            else {
                "detail": "No active account found with the given credentials"
            }
        )
        response = httpx.Response(
            status_code=status,
            content=json.dumps(body).encode(),
            headers={"content-type": "application/json"},
            request=httpx.Request("POST", "http://testserver/api/token/"),
        )
        return mocker.patch.object(client._http, "post", return_value=response)

    return _patch
