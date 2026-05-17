"""
Tests for import_bofa_live helpers and the import_bofa_saved CLI.

Focused on the truncated-description resolution path: BofA's web UI
truncates long ACH descriptions with a trailing '...' (e.g.
'FICTITIOUS BANK DES:TRANSFER ID:XXXXX0000001 INDN:Test Holder CO...'
instead of the full
'FICTITIOUS BANK DES:TRANSFER ID:XXXXX0000001 INDN:Test Holder CO ID:XXXXX00001 WEB').
When a prior CSV import stored the full description, the dedup key
mismatches on the next scrape run and a duplicate transaction is created.
``_resolve_truncated_descriptions`` fixes this before the dedup comparison.
Both ``import_bofa_live`` and ``import_bofa_saved`` must call it.
"""

# system imports
import json
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

# 3rd party imports
import pytest
from click.testing import CliRunner
from pytest_mock import MockerFixture

# Project imports
import importers.import_bofa_saved as ibs
from importers.import_bofa_live import _resolve_truncated_descriptions
from importers.import_bofa_saved import cli_cmd as bofa_saved_cmd
from importers.parsers.common import ParsedStatement, ParsedTransaction

# ---------------------------------------------------------------------------
# Shared test data -- fully synthetic, no real account IDs or names
# ---------------------------------------------------------------------------

_TX_DATE = date(2024, 3, 15)
_AMOUNT = Decimal("500.00")

FULL_DESC = (
    "FICTITIOUS BANK DES:TRANSFER ID:XXXXX0000001 "
    "INDN:Test Holder CO ID:XXXXX00001 WEB"
)
# BofA truncates the description at the space before 'CO ID:...'
TRUNCATED_DESC = (
    "FICTITIOUS BANK DES:TRANSFER ID:XXXXX0000001 INDN:Test Holder CO..."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


####################################################################
#
def _make_statement(
    desc: str,
    *,
    tx_date: date = _TX_DATE,
    amount: Decimal = _AMOUNT,
    bank_tx_id: str | None = None,
    balance: Decimal = Decimal("1000.00"),
) -> ParsedStatement:
    """Build a minimal single-transaction ParsedStatement."""
    tx = ParsedTransaction(
        transaction_date=tx_date,
        raw_description=desc,
        amount=amount,
        running_balance=(balance + amount).quantize(Decimal("0.01")),
        transaction_type="deposit",
        pending=False,
        bank_transaction_id=bank_tx_id,
    )
    return ParsedStatement(
        beginning_balance=balance,
        beginning_date=tx_date,
        ending_balance=(balance + amount).quantize(Decimal("0.01")),
        ending_date=tx_date,
        total_credits=amount if amount > 0 else Decimal("0"),
        total_debits=amount if amount < 0 else Decimal("0"),
        transactions=[tx],
    )


####################################################################
#
def _existing_map(
    desc: str,
    *,
    tx_date: date = _TX_DATE,
    amount: Decimal = _AMOUNT,
    tx_id: str = "tx-0001",
    tx_type: str = "deposit",
    bank_tx_id: str = "",
) -> dict[tuple[str, str, str], list[tuple[str, str, str]]]:
    """Build a minimal ``_fetch_existing``-style dedup map."""
    key = (tx_date.isoformat(), str(amount.quantize(Decimal("0.01"))), desc)
    return {key: [(tx_id, tx_type, bank_tx_id)]}


########################################################################
########################################################################
#
class TestResolveTruncatedDescriptions:
    """Unit tests for ``_resolve_truncated_descriptions``."""

    ####################################################################
    #
    def test_truncated_description_resolved_and_bank_tx_id_preserved(
        self,
    ) -> None:
        """
        GIVEN: An existing transaction stored with the full ACH description
               and a scraped transaction with the same date/amount but a
               BofA-truncated '...' description.  The scraped transaction
               carries a bank_transaction_id.
        WHEN:  ``_resolve_truncated_descriptions`` is called.
        THEN:  The truncated description is replaced with the full one AND
               the bank_transaction_id is carried through unchanged.
        """
        stmt = _make_statement(TRUNCATED_DESC, bank_tx_id="deadbeef1234")
        existing = _existing_map(FULL_DESC)

        result = _resolve_truncated_descriptions(stmt, existing)

        tx = result.transactions[0]
        assert tx.raw_description == FULL_DESC
        assert tx.bank_transaction_id == "deadbeef1234"

    ####################################################################
    #
    @pytest.mark.parametrize(
        "scraped_desc,existing_date,expected_desc",
        [
            pytest.param(
                FULL_DESC,
                _TX_DATE,
                FULL_DESC,
                id="exact-key-match",
            ),
            pytest.param(
                TRUNCATED_DESC,
                date(2024, 1, 1),  # different date -- no candidate found
                TRUNCATED_DESC,
                id="no-candidate",
            ),
        ],
    )
    def test_description_unchanged_when_no_resolution(
        self,
        scraped_desc: str,
        existing_date: date,
        expected_desc: str,
    ) -> None:
        """
        GIVEN: A scraped transaction that either already matches the exact
               dedup key (non-truncated description, 'exact-key-match') or
               has a truncated description but no existing entry at the same
               date/amount ('no-candidate').
        WHEN:  ``_resolve_truncated_descriptions`` is called.
        THEN:  The description is left unchanged in both cases.
        """
        stmt = _make_statement(scraped_desc)
        existing = _existing_map(FULL_DESC, tx_date=existing_date)

        result = _resolve_truncated_descriptions(stmt, existing)

        assert result.transactions[0].raw_description == expected_desc


# ---------------------------------------------------------------------------
# FakeClient for import_bofa_saved integration tests
# ---------------------------------------------------------------------------


########################################################################
########################################################################
#
class _FakeClient:
    """Minimal in-memory stand-in for ``MibudgeClient``."""

    ####################################################################
    #
    def __init__(self) -> None:
        self.accounts: dict[str, dict[str, Any]] = {}
        self.transactions: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, str, Any]] = []
        self._next_id = 0

    ####################################################################
    #
    def _mint_id(self, prefix: str) -> str:
        self._next_id += 1
        return f"{prefix}-{self._next_id:04d}"

    ####################################################################
    #
    def authenticate(self) -> None:
        self.calls.append(("AUTH", "/api/token/", None))

    ####################################################################
    #
    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self.calls.append(("GET", path, params))
        if path == "/api/v1/users/me/":
            return {"timezone": "UTC"}
        if path.startswith("/api/v1/bank-accounts/") and path.endswith("/"):
            acct_id = path.rstrip("/").rsplit("/", 1)[-1]
            if acct_id in self.accounts:
                return self.accounts[acct_id]
        raise KeyError(f"_FakeClient.get: unhandled {path!r}")

    ####################################################################
    #
    def get_all(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        page_size: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        self.calls.append(("GET_ALL", path, params))
        if path == "/api/v1/bank-accounts/":
            yield from self.accounts.values()
            return
        if path == "/api/v1/transactions/":
            bank_acct = (params or {}).get("bank_account")
            pending_filter = (params or {}).get("pending")
            for tx in self.transactions.values():
                if bank_acct and tx.get("bank_account") != bank_acct:
                    continue
                # Honour pending=true so _resolve_pending_transactions does
                # not see settled (CSV-imported) rows as pending candidates.
                if pending_filter == "true" and not tx.get("pending", False):
                    continue
                yield tx
            return
        raise KeyError(f"_FakeClient.get_all: unhandled {path!r}")

    ####################################################################
    #
    def post(self, path: str, json: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("POST", path, json))
        if path == "/api/v1/transactions/":
            tx_id = self._mint_id("tx")
            row = {"id": tx_id, **json}
            self.transactions[tx_id] = row
            return row
        if "/mark-imported/" in path or "/resolve-pending/" in path:
            return {}
        raise KeyError(f"_FakeClient.post: unhandled {path!r}")

    ####################################################################
    #
    def patch(self, path: str, json: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("PATCH", path, json))
        if path.startswith("/api/v1/transactions/") and path.endswith("/"):
            tx_id = path.rstrip("/").rsplit("/", 1)[-1]
            if tx_id in self.transactions:
                self.transactions[tx_id].update(json)
                return self.transactions[tx_id]
        raise KeyError(f"_FakeClient.patch: unhandled {path!r}")

    ####################################################################
    #
    def close(self) -> None:
        pass

    ####################################################################
    #
    def __enter__(self) -> "_FakeClient":
        return self

    ####################################################################
    #
    def __exit__(self, *args: Any) -> None:
        self.close()


####################################################################
#
def _seed_account(
    fake: _FakeClient,
    *,
    last_four: str = "0000",
    posted_balance: str = "1000.00",
) -> dict[str, Any]:
    """Seed a BankAccount into the fake matching ``last_four``."""
    acct_id = fake._mint_id("acct")
    row: dict[str, Any] = {
        "id": acct_id,
        "name": f"TEST CHECKING - {last_four}",
        "account_number": last_four,
        "account_type": "C",
        "posted_balance": posted_balance,
        "available_balance": posted_balance,
    }
    fake.accounts[acct_id] = row
    return row


####################################################################
#
def _seed_transaction(
    fake: _FakeClient,
    account_id: str,
    *,
    tx_date: date = _TX_DATE,
    amount: Decimal = _AMOUNT,
    desc: str = FULL_DESC,
    bank_tx_id: str = "",
) -> dict[str, Any]:
    """Seed a settled transaction (simulates a prior CSV import)."""
    tx_id = fake._mint_id("tx")
    row: dict[str, Any] = {
        "id": tx_id,
        "bank_account": account_id,
        "posted_date": f"{tx_date.isoformat()}T00:00:00Z",
        "amount": str(amount.quantize(Decimal("0.01"))),
        "raw_description": desc,
        "transaction_type": "deposit",
        "pending": False,
        "bank_transaction_id": bank_tx_id,
    }
    fake.transactions[tx_id] = row
    return row


####################################################################
#
def _write_scrape_json(
    path: Path,
    *,
    last_four: str = "0000",
    tx_date_str: str = "03/15/2024",
    amount: str = "500.00",
    desc: str = FULL_DESC,
    ending_balance: str = "1500.00",
    running_balance: str = "1500.00",
    txn_hash: str = "aabbccdd0000",
) -> None:
    """Write a minimal saved-scrape JSON file to ``path``."""
    data = {
        "format_version": 2,
        "scraped_at": "2024-03-16T10:00:00",
        "account_name": f"TEST CHECKING - {last_four}",
        "ending_balance": ending_balance,
        "transactions": [
            {
                "date": tx_date_str,
                "desc": desc,
                "amount": amount,
                "type": "Deposit",
                "txn_hash": txn_hash,
                "running_balance": running_balance,
            }
        ],
    }
    path.write_text(json.dumps(data), encoding="utf-8")


########################################################################
########################################################################
#
@pytest.fixture
def fake_client(mocker: MockerFixture) -> _FakeClient:
    """Patch ``_build_client`` in import_bofa_saved's namespace so the CLI
    receives a ``_FakeClient`` rather than building a real httpx client."""
    fc = _FakeClient()
    mocker.patch.object(ibs, "_build_client", return_value=fc)
    return fc


####################################################################
#
def _run(*args: str) -> Any:
    """Invoke ``import_bofa_saved`` with credentials stubbed out."""
    runner = CliRunner()
    env = {
        "MIBUDGE_URL": "http://testserver",
        "MIBUDGE_USERNAME": "u",
        "MIBUDGE_PASSWORD": "p",
    }
    return runner.invoke(
        bofa_saved_cmd,
        ["--plain", *args],
        env=env,
        catch_exceptions=False,
    )


########################################################################
########################################################################
#
class TestImportBofaSavedTruncatedDescription:
    """
    Integration tests for ``import_bofa_saved`` truncated-description dedup.
    """

    ####################################################################
    #
    @pytest.mark.parametrize(
        "seed_csv_tx,scrape_desc,expected_posts",
        [
            pytest.param(
                True,
                TRUNCATED_DESC,
                0,
                id="truncated-dedup",
            ),
            pytest.param(
                False,
                FULL_DESC,
                1,
                id="new-import",
            ),
        ],
    )
    def test_import_result(
        self,
        fake_client: _FakeClient,
        tmp_path: Path,
        seed_csv_tx: bool,
        scrape_desc: str,
        expected_posts: int,
    ) -> None:
        """
        GIVEN ('truncated-dedup'): A transaction previously imported from a
               BofA CSV with the full ACH description and no bank_transaction_id
               (CSV imports predate that field); the saved scrape for the same
               transaction uses the BofA-truncated '...' form.
        GIVEN ('new-import'): No prior import exists for the account.
        WHEN:  ``import_bofa_saved`` processes the scrape file.
        THEN:  'truncated-dedup' -- the truncated scrape transaction is
               recognised as a duplicate and no new transaction is POSTed.
               'new-import' -- exactly one new transaction is POSTed.
        """
        acct = _seed_account(fake_client, last_four="0000")
        if seed_csv_tx:
            _seed_transaction(fake_client, acct["id"])

        scrape_path = tmp_path / "2024-03-16-100000-0000.json"
        _write_scrape_json(scrape_path, last_four="0000", desc=scrape_desc)

        result = _run(str(scrape_path))

        assert result.exit_code == 0, result.output
        new_tx_posts = [
            c
            for c in fake_client.calls
            if c[0] == "POST" and c[1] == "/api/v1/transactions/"
        ]
        assert len(new_tx_posts) == expected_posts, (
            f"Expected {expected_posts} new transaction(s), "
            f"got {len(new_tx_posts)}.\nCLI output:\n{result.output}"
        )
