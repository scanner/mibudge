"""
Fixtures for importer tests.

``bofa_csv_factory`` generates a syntactically valid Bank of America CSV
export file from parameters (date range, balances, transaction count) so that
tests never rely on real financial data committed to the repository.

``client`` provides a pre-configured MibudgeClient pointed at a test server.

``mock_auth`` returns a factory that patches a client's token endpoint so
tests do not need to inline the full mocker.patch.object call each time.
"""

# system imports
import csv
import io
import json
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import NamedTuple
from unittest.mock import MagicMock

# 3rd party imports
import httpx
import pytest
from faker import Faker
from pytest_mock import MockerFixture

# Project imports
from importers.client import MibudgeClient


########################################################################
########################################################################
#
class BofaCSVRow(NamedTuple):
    """A single generated transaction row."""

    transaction_date: date
    description: str
    amount: Decimal
    running_balance: Decimal


####################################################################
#
def _fmt_amount(value: Decimal) -> str:
    """Format a Decimal as a BofA amount string (comma thousands, 2dp)."""
    # Use Python's built-in formatting; the CSV writer will quote it.
    quantized = value.quantize(Decimal("0.01"))
    # Produce "1,234.56" or "-1,234.56".
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

    # Summary section
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

    # Blank line separator
    buf.write("\n")

    # Transaction section header
    w.writerow(["Date", "Description", "Amount", "Running Bal."])

    # Beginning balance row (no Amount column)
    w.writerow(
        [
            f"{beginning_date:%m/%d/%Y}",
            f"Beginning balance as of {beginning_date:%m/%d/%Y}",
            "",
            _fmt_amount(beginning_balance),
        ]
    )

    # Transaction rows
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
    faker: Faker, tmp_path: Path
) -> Callable[..., tuple[Path, list[BofaCSVRow]]]:
    """
    Return a factory that generates a BofA-format CSV file.

    The factory signature is::

        bofa_csv_factory(
            num_transactions: int = 10,
            beginning_balance: Decimal | float | str = "1000.00",
            start_date: date | None = None,   # defaults to 90 days ago
            end_date: date | None = None,     # defaults to today
        ) -> tuple[Path, list[BofaCSVRow]]

    Returns a ``(path, rows)`` tuple where ``path`` is the generated CSV
    file (in a temporary directory) and ``rows`` is the list of generated
    transaction rows in order, for use in test assertions.

    Transaction amounts are randomly generated so that the running balance
    stays positive throughout. Total credits and total debits are derived
    from the rows, not independently generated.
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

        # Spread transaction dates evenly across the range.
        date_range = (end - start).days or 1
        step = max(date_range // max(num_transactions, 1), 1)

        # Sample transaction descriptions covering known type patterns so
        # tests can assert on type inference as well as parsing.
        description_templates = [
            lambda: f"{faker.company().upper()} {faker.past_date(start_date='-30d'):%m/%d} PURCHASE {faker.city().upper()} {faker.state_abbr()}",
            lambda: f"TST*{faker.company().upper()} {faker.past_date(start_date='-30d'):%m/%d} MOBILE PURCHASE {faker.city().upper()} {faker.state_abbr()}",
            lambda: f"SQ *{faker.company().upper()} {faker.past_date(start_date='-30d'):%m/%d} PURCHASE {faker.city().upper()} {faker.state_abbr()}",
            lambda: f"{faker.company()} DES:PAYROLL ID:CER{faker.numerify('######')} INDN:{faker.name().upper()} CO ID:{faker.numerify('######')} PPD",
            lambda: f"{faker.company()} DES:{faker.bothify('??-######')} ID:{faker.bothify('??????????')} INDN:{faker.name().upper()} CO ID:{faker.numerify('######')} CCD",
            lambda: f"Online Banking transfer from CHK {faker.numerify('####')} Confirmation# {faker.numerify('#####')}",
            lambda: f"ATM WITHDRAWAL {faker.past_date(start_date='-30d'):%m/%d} {faker.city().upper()} {faker.state_abbr()}",
        ]

        rows: list[BofaCSVRow] = []
        for i in range(num_transactions):
            tx_date = start + timedelta(days=i * step)
            if tx_date > end:
                tx_date = end

            description = description_templates[
                i % len(description_templates)
            ]()

            # Alternate debits and credits; keep balance positive.
            if i % 3 == 2:
                # Credit
                amount = Decimal(
                    str(
                        faker.pyfloat(
                            min_value=50, max_value=2000, right_digits=2
                        )
                    )
                ).quantize(Decimal("0.01"))
            else:
                # Debit -- ensure it doesn't exceed current balance.
                max_debit = float(
                    min(balance - Decimal("1.00"), Decimal("500.00"))
                )
                if max_debit < 1.0:
                    amount = Decimal("1.00")
                else:
                    amount = -Decimal(
                        str(
                            faker.pyfloat(
                                min_value=1, max_value=max_debit, right_digits=2
                            )
                        )
                    ).quantize(Decimal("0.01"))

            balance = (balance + amount).quantize(Decimal("0.01"))
            rows.append(
                BofaCSVRow(
                    transaction_date=tx_date,
                    description=description,
                    amount=amount,
                    running_balance=balance,
                )
            )

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


########################################################################
########################################################################
#
@pytest.fixture
def client() -> MibudgeClient:
    """Return a MibudgeClient pre-configured to talk to the test server."""
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
