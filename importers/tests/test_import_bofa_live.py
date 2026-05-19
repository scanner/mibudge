"""
Tests for import_bofa_live helpers and the import_bofa_saved CLI.

Covers the pending-transaction dedup pipeline introduced to handle BofA's
unstable txn_hash (changes on every scrape for every transaction) and the
shifting posted_date for pending rows (always today(), so re-runs on a
different calendar day produce duplicates via the standard date+amount+desc
key).

Also covers the truncated-description resolution path: BofA's web UI
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
from importers.import_bofa_live import (
    _filter_existing_pending,
    _get_variable_amount_descs,
    _normalize_description,
    _pending_desc_matches,
    _resolve_pending_transactions,
    _resolve_truncated_descriptions,
)
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
) -> dict[tuple[str, str, str], list[tuple[str, str]]]:
    """Build a minimal ``_fetch_existing``-style dedup map."""
    key = (tx_date.isoformat(), str(amount.quantize(Decimal("0.01"))), desc)
    return {key: [(tx_id, tx_type)]}


########################################################################
########################################################################
#
class TestResolveTruncatedDescriptions:
    """Unit tests for ``_resolve_truncated_descriptions``."""

    ####################################################################
    #
    def test_truncated_description_resolved(self) -> None:
        """
        GIVEN: An existing transaction stored with the full ACH description
               and a scraped transaction with the same date/amount but a
               BofA-truncated '...' description.
        WHEN:  ``_resolve_truncated_descriptions`` is called.
        THEN:  The truncated description is replaced with the full one.
        """
        stmt = _make_statement(TRUNCATED_DESC)
        existing = _existing_map(FULL_DESC)

        result = _resolve_truncated_descriptions(stmt, existing)

        assert result.transactions[0].raw_description == FULL_DESC

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
        if "/mark-imported/" in path:
            return {}
        if "/resolve-pending/" in path:
            # Simulate the server: mark pending->posted and apply any field
            # updates (posted_date, amount) so that subsequent _fetch_existing
            # queries see the resolved transaction in its settled state.
            tx_id = path.rstrip("/").rsplit("/", 2)[-2]
            if tx_id in self.transactions:
                self.transactions[tx_id].update({"pending": False, **json})
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


# ---------------------------------------------------------------------------
# Pending-transaction dedup helpers
# ---------------------------------------------------------------------------

# Real BofA UI noise text appended after <br> for restaurant-style pending txns.
_AMOUNT_MAY_CHANGE = (
    "Amount may change - waiting for final amount from merchant"
)

# Stable pending description (no BofA noise).
_STABLE_DESC = "CHECKCARD ACLU 800-7XX-2240 NY ON 05/15"

# Restaurant-style description -- the part before the <br> break.
_RESTAURANT_DESC = "PURCHASE CURRY PIZZA HOUSE +XXXXX623558 ON 05/15"

# The full noisy string as stored in the DB by the old _normalize_description
# (which joined ALL whitespace tokens including the post-\n text).
_RESTAURANT_DESC_NOISY = f"{_RESTAURANT_DESC} {_AMOUNT_MAY_CHANGE}"

# The raw string as the scraper returns it (newline between parts).
_RESTAURANT_RAW = f"{_RESTAURANT_DESC}\n{_AMOUNT_MAY_CHANGE}"


########################################################################
########################################################################
#
class TestNormalizeDescription:
    """Unit tests for ``_normalize_description``."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "text,expected",
        [
            pytest.param(
                "FOO BAR",
                "FOO BAR",
                id="plain-no-change",
            ),
            pytest.param(
                "FOO  BAR",
                "FOO BAR",
                id="internal-whitespace-collapsed",
            ),
            pytest.param(
                "  FOO  ",
                "FOO",
                id="leading-trailing-stripped",
            ),
            pytest.param(
                "FOO\tBAR",
                "FOO BAR",
                id="tabs-collapsed",
            ),
            pytest.param(
                _RESTAURANT_RAW,
                _RESTAURANT_DESC,
                id="amount-may-change-noise-stripped",
            ),
            pytest.param(
                f"  {_RESTAURANT_DESC}  \n{_AMOUNT_MAY_CHANGE}",
                _RESTAURANT_DESC,
                id="noise-stripped-with-leading-trailing",
            ),
            pytest.param(
                f"{_STABLE_DESC}\nsome other noise",
                _STABLE_DESC,
                id="any-newline-noise-stripped",
            ),
        ],
    )
    def test_normalize_description(self, text: str, expected: str) -> None:
        """
        GIVEN: A raw description string from the BofA scraper.
        WHEN:  ``_normalize_description`` is called.
        THEN:  The result has leading/trailing whitespace stripped, internal
               whitespace collapsed, and everything from the first newline
               (BofA's <br> tag) onwards removed.
        """
        assert _normalize_description(text) == expected


########################################################################
########################################################################
#
class TestPendingDescMatches:
    """Unit tests for ``_pending_desc_matches``."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "db_desc,scraped_desc,expected",
        [
            pytest.param(
                _STABLE_DESC,
                _STABLE_DESC,
                True,
                id="exact-match",
            ),
            pytest.param(
                _RESTAURANT_DESC_NOISY,
                _RESTAURANT_DESC,
                True,
                id="amount-may-change-noisy-db-prefix-match",
            ),
            pytest.param(
                f"{_STABLE_DESC} some extra words",
                _STABLE_DESC,
                True,
                id="any-space-separated-suffix-matches",
            ),
            pytest.param(
                # "FOOBAR" does NOT start with "FOO " -- must be space-separated.
                "FOOBAR",
                "FOO",
                False,
                id="no-space-after-prefix-no-match",
            ),
            pytest.param(
                "AMAZON",
                "AMAZON.COM",
                False,
                id="db-shorter-than-scraped-no-match",
            ),
            pytest.param(
                _RESTAURANT_DESC,
                _RESTAURANT_DESC_NOISY,
                False,
                id="scraped-is-noisy-db-is-clean-no-match",
            ),
            pytest.param(
                "",
                "",
                True,
                id="empty-strings",
            ),
        ],
    )
    def test_pending_desc_matches(
        self, db_desc: str, scraped_desc: str, expected: bool
    ) -> None:
        """
        GIVEN: A DB description and a clean scraped description.
        WHEN:  ``_pending_desc_matches`` is called.
        THEN:  Returns True for exact matches and for DB entries that are
               the scraped description followed by a space and arbitrary
               suffix (the pre-fix noisy format).  Returns False otherwise.
        """
        assert _pending_desc_matches(db_desc, scraped_desc) == expected


########################################################################
########################################################################
#


class _StubScrapeTx:
    """Minimal scraped-transaction stand-in for ``_get_variable_amount_descs``."""

    def __init__(self, date: str, desc: str) -> None:
        self.date = date
        self.desc = desc
        self.amount = "0.00"
        self.type = "Debit"
        self.txn_hash = ""
        self.running_balance = "0.00"


class _StubScrapeAccount:
    """Minimal account stand-in exposing ``get_transactions()``."""

    def __init__(self, txs: list[_StubScrapeTx]) -> None:
        self._txs = txs

    def get_transactions(self) -> list[_StubScrapeTx]:
        return self._txs


########################################################################
########################################################################
#
class TestGetVariableAmountDescs:
    """Unit tests for ``_get_variable_amount_descs``."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "date_str,desc,expected_in_result",
        [
            pytest.param(
                "Processing",
                _RESTAURANT_RAW,
                True,
                id="pending-with-newline-included",
            ),
            pytest.param(
                "Processing",
                _STABLE_DESC,
                False,
                id="pending-without-newline-excluded",
            ),
            pytest.param(
                "05/15/2026",
                _RESTAURANT_RAW,
                False,
                id="settled-with-newline-excluded",
            ),
        ],
    )
    def test_variable_amount_classification(
        self, date_str: str, desc: str, expected_in_result: bool
    ) -> None:
        """
        GIVEN: A scraped transaction with a given date string and description.
        WHEN:  ``_get_variable_amount_descs`` is called.
        THEN:  The normalized description is included only when the
               transaction is pending (date unparseable) AND its raw
               description contains a newline (BofA's <br> noise marker).
        """
        account = _StubScrapeAccount([_StubScrapeTx(date_str, desc)])
        result = _get_variable_amount_descs(account)
        normalized = _normalize_description(desc)
        assert (normalized in result) == expected_in_result

    ####################################################################
    #
    def test_multiple_transactions_only_variable_returned(self) -> None:
        """
        GIVEN: An account with a mix of pending+noisy, pending+clean, and
               settled+noisy transactions.
        WHEN:  ``_get_variable_amount_descs`` is called.
        THEN:  Only the pending+noisy description is in the result set.
        """
        txs = [
            _StubScrapeTx("Processing", _RESTAURANT_RAW),  # variable pending
            _StubScrapeTx("Processing", _STABLE_DESC),  # stable pending
            _StubScrapeTx(
                "05/15/2026", _RESTAURANT_RAW
            ),  # settled, not variable
        ]
        account = _StubScrapeAccount(txs)
        result = _get_variable_amount_descs(account)
        assert result == {_RESTAURANT_DESC}


# ---------------------------------------------------------------------------
# Helpers for _filter_existing_pending unit tests
# ---------------------------------------------------------------------------

_ACCT_ID = "acct-0001"
_STABLE_AMOUNT = Decimal("-25.00")
_RESTAURANT_AMOUNT_V1 = Decimal("-134.82")
_RESTAURANT_AMOUNT_V2 = Decimal("-142.00")  # final charge differs from auth


####################################################################
#
def _make_pending_tx(
    desc: str,
    amount: Decimal,
    *,
    tx_date: date | None = None,
) -> ParsedTransaction:
    """Build a pending ``ParsedTransaction``."""
    d = tx_date or date.today()
    return ParsedTransaction(
        transaction_date=d,
        raw_description=desc,
        amount=amount,
        running_balance=(Decimal("1000.00") + amount).quantize(Decimal("0.01")),
        transaction_type="purchase",
        pending=True,
    )


####################################################################
#
def _make_pending_statement(
    *pending_txs: ParsedTransaction,
    settled_txs: list[ParsedTransaction] | None = None,
) -> ParsedStatement:
    """Build a ``ParsedStatement`` containing the given pending transactions."""
    all_txs = list(settled_txs or []) + list(pending_txs)
    return ParsedStatement(
        beginning_balance=Decimal("1000.00"),
        beginning_date=date.today(),
        ending_balance=Decimal("1000.00"),
        ending_date=date.today(),
        total_credits=Decimal("0"),
        total_debits=Decimal("0"),
        transactions=all_txs,
    )


####################################################################
#
def _make_db_pending_row(desc: str, amount: Decimal) -> dict[str, Any]:
    """Build a minimal DB pending-transaction dict as returned by the API."""
    return {
        "id": "tx-db-001",
        "bank_account": _ACCT_ID,
        "raw_description": desc,
        "amount": str(amount.quantize(Decimal("0.01"))),
        "pending": True,
        "posted_date": "2026-05-17T00:00:00Z",
    }


########################################################################
########################################################################
#


class _StubClient:
    """Minimal client stub for pending-dedup unit tests."""

    def __init__(self, db_rows: list[dict[str, Any]]) -> None:
        self._rows = db_rows
        self.get_all_called = False
        self.posts: list[tuple[str, dict[str, Any]]] = []

    def get_all(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        page_size: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        self.get_all_called = True
        return iter(self._rows)

    def post(self, path: str, json: dict[str, Any]) -> dict[str, Any]:
        self.posts.append((path, json))
        return {}


########################################################################
########################################################################
#
class TestFilterExistingPending:
    """Unit tests for ``_filter_existing_pending``."""

    ####################################################################
    #
    def test_no_scraped_pending_returns_early_without_client_call(
        self,
    ) -> None:
        """
        GIVEN: A statement with no pending transactions (only settled).
        WHEN:  ``_filter_existing_pending`` is called.
        THEN:  Returns immediately without calling the client, and skipped=0.
        """
        settled = ParsedTransaction(
            transaction_date=_TX_DATE,
            raw_description=_STABLE_DESC,
            amount=_STABLE_AMOUNT,
            running_balance=Decimal("975.00"),
            transaction_type="purchase",
            pending=False,
        )
        stmt = _make_pending_statement(settled_txs=[settled])
        stub = _StubClient([])

        result_stmt, skipped = _filter_existing_pending(stmt, _ACCT_ID, stub)

        assert not stub.get_all_called
        assert skipped == 0
        assert len(result_stmt.transactions) == 1

    ####################################################################
    #
    def test_no_db_pending_all_scraped_pass_through(self) -> None:
        """
        GIVEN: A scraped pending transaction with no matching DB pending rows.
        WHEN:  ``_filter_existing_pending`` is called.
        THEN:  The pending transaction is not consumed; skipped=0.
        """
        tx = _make_pending_tx(_STABLE_DESC, _STABLE_AMOUNT)
        stmt = _make_pending_statement(tx)
        stub = _StubClient([])

        result_stmt, skipped = _filter_existing_pending(stmt, _ACCT_ID, stub)

        assert skipped == 0
        assert len(result_stmt.transactions) == 1

    ####################################################################
    #
    def test_stable_amount_exact_match_consumed(self) -> None:
        """
        GIVEN: A stable-amount pending tx scraped again on a later calendar
               day (date shifts, same desc and amount).
        WHEN:  ``_filter_existing_pending`` is called.
        THEN:  The already-imported pending is consumed and skipped=1.
        """
        tx = _make_pending_tx(_STABLE_DESC, _STABLE_AMOUNT)
        stmt = _make_pending_statement(tx)
        db_row = _make_db_pending_row(_STABLE_DESC, _STABLE_AMOUNT)
        stub = _StubClient([db_row])

        result_stmt, skipped = _filter_existing_pending(stmt, _ACCT_ID, stub)

        assert skipped == 1
        assert all(not t.pending for t in result_stmt.transactions)

    ####################################################################
    #
    def test_stable_amount_different_amount_not_consumed(self) -> None:
        """
        GIVEN: A stable-amount pending tx whose amount differs from the
               DB entry (not the same transaction -- not a variable-amount
               restaurant charge).
        WHEN:  ``_filter_existing_pending`` is called.
        THEN:  The transaction is NOT consumed; it is imported as new.
        """
        tx = _make_pending_tx(_STABLE_DESC, Decimal("-30.00"))
        stmt = _make_pending_statement(tx)
        db_row = _make_db_pending_row(_STABLE_DESC, _STABLE_AMOUNT)
        stub = _StubClient([db_row])

        result_stmt, skipped = _filter_existing_pending(stmt, _ACCT_ID, stub)

        assert skipped == 0
        assert len([t for t in result_stmt.transactions if t.pending]) == 1

    ####################################################################
    #
    @pytest.mark.parametrize(
        "db_desc,scraped_desc",
        [
            pytest.param(
                _RESTAURANT_DESC,
                _RESTAURANT_DESC,
                id="clean-db-clean-scrape",
            ),
            pytest.param(
                _RESTAURANT_DESC_NOISY,
                _RESTAURANT_DESC,
                id="noisy-db-clean-scrape-amount-may-change",
            ),
        ],
    )
    def test_variable_amount_matched_despite_different_amount(
        self, db_desc: str, scraped_desc: str
    ) -> None:
        """
        GIVEN: A restaurant-style pending transaction whose final charge
               differs from the authorization amount; the DB entry may have
               the pre-fix noisy description with "Amount may change..."
               appended (clean-db case tests a post-fix DB entry).
        WHEN:  ``_filter_existing_pending`` is called with the description
               in ``variable_amount_descs``.
        THEN:  The already-imported pending is consumed despite the amount
               difference, because amount is not required to match for
               variable-amount transactions.
        """
        tx = _make_pending_tx(scraped_desc, _RESTAURANT_AMOUNT_V2)
        stmt = _make_pending_statement(tx)
        db_row = _make_db_pending_row(db_desc, _RESTAURANT_AMOUNT_V1)
        stub = _StubClient([db_row])

        result_stmt, skipped = _filter_existing_pending(
            stmt, _ACCT_ID, stub, variable_amount_descs={scraped_desc}
        )

        assert skipped == 1
        assert all(not t.pending for t in result_stmt.transactions)

    ####################################################################
    #
    def test_variable_amount_not_in_set_requires_amount_match(self) -> None:
        """
        GIVEN: A pending tx whose description is NOT in ``variable_amount_descs``
               and whose amount differs from the DB entry.
        WHEN:  ``_filter_existing_pending`` is called.
        THEN:  The transaction is NOT consumed (amount must match for stable
               transactions).
        """
        tx = _make_pending_tx(_RESTAURANT_DESC, _RESTAURANT_AMOUNT_V2)
        stmt = _make_pending_statement(tx)
        db_row = _make_db_pending_row(_RESTAURANT_DESC, _RESTAURANT_AMOUNT_V1)
        stub = _StubClient([db_row])

        result_stmt, skipped = _filter_existing_pending(
            stmt, _ACCT_ID, stub, variable_amount_descs=set()
        )

        assert skipped == 0

    ####################################################################
    #
    def test_count_aware_two_scraped_one_db(self) -> None:
        """
        GIVEN: Two pending transactions with identical description/amount
               (e.g. two coffee purchases) but only one already in the DB.
        WHEN:  ``_filter_existing_pending`` is called.
        THEN:  Exactly one is consumed and one passes through as new.
        """
        tx1 = _make_pending_tx(_STABLE_DESC, _STABLE_AMOUNT)
        tx2 = _make_pending_tx(_STABLE_DESC, _STABLE_AMOUNT)
        stmt = _make_pending_statement(tx1, tx2)
        db_row = _make_db_pending_row(_STABLE_DESC, _STABLE_AMOUNT)
        stub = _StubClient([db_row])

        result_stmt, skipped = _filter_existing_pending(stmt, _ACCT_ID, stub)

        assert skipped == 1
        pending_left = [t for t in result_stmt.transactions if t.pending]
        assert len(pending_left) == 1

    ####################################################################
    #
    def test_settled_transactions_preserved(self) -> None:
        """
        GIVEN: A statement with one settled transaction and one pending
               transaction that is already in the DB.
        WHEN:  ``_filter_existing_pending`` is called.
        THEN:  The settled transaction is preserved unchanged; the pending
               is consumed.
        """
        settled = ParsedTransaction(
            transaction_date=_TX_DATE,
            raw_description=FULL_DESC,
            amount=_AMOUNT,
            running_balance=Decimal("1500.00"),
            transaction_type="deposit",
            pending=False,
        )
        pending = _make_pending_tx(_STABLE_DESC, _STABLE_AMOUNT)
        stmt = _make_pending_statement(pending, settled_txs=[settled])
        db_row = _make_db_pending_row(_STABLE_DESC, _STABLE_AMOUNT)
        stub = _StubClient([db_row])

        result_stmt, skipped = _filter_existing_pending(stmt, _ACCT_ID, stub)

        assert skipped == 1
        remaining = result_stmt.transactions
        assert len(remaining) == 1
        assert not remaining[0].pending
        assert remaining[0].raw_description == FULL_DESC


########################################################################
########################################################################
#


# Settle date used in _resolve_pending_transactions unit tests.
_SETTLE_DATE = date(2026, 5, 20)
_PENDING_DATE_STR = "2026-05-17T00:00:00Z"  # posted_date of pending DB row


####################################################################
#
def _make_settled_statement(
    desc: str,
    amount: Decimal,
    *,
    tx_date: date = _SETTLE_DATE,
) -> ParsedStatement:
    """Build a minimal statement containing one settled transaction."""
    tx = ParsedTransaction(
        transaction_date=tx_date,
        raw_description=desc,
        amount=amount,
        running_balance=Decimal("1000.00"),
        transaction_type="purchase",
        pending=False,
    )
    return ParsedStatement(
        beginning_balance=Decimal("1000.00"),
        beginning_date=tx_date,
        ending_balance=Decimal("1000.00"),
        ending_date=tx_date,
        total_credits=Decimal("0"),
        total_debits=abs(amount),
        transactions=[tx],
    )


####################################################################
#
def _make_pending_db_row(
    desc: str,
    amount: Decimal,
    *,
    posted_date: str = _PENDING_DATE_STR,
) -> dict[str, Any]:
    """Build a pending DB row as returned by the API for resolve tests."""
    return {
        "id": "db-pending-001",
        "bank_account": _ACCT_ID,
        "raw_description": desc,
        "amount": str(amount.quantize(Decimal("0.01"))),
        "amount_currency": "USD",
        "pending": True,
        "posted_date": posted_date,
    }


########################################################################
########################################################################
#
class TestResolvePendingTransactions:
    """Unit tests for ``_resolve_pending_transactions``.

    Focused on description matching: ensures that DB pending rows whose
    description contains pre-fix noise ("Amount may change...") are
    correctly matched against clean settled scraped descriptions.
    """

    ####################################################################
    #
    @pytest.mark.parametrize(
        "db_desc,settle_desc,expected_resolved,expected_amount_changed",
        [
            pytest.param(
                _STABLE_DESC,
                _STABLE_DESC,
                1,
                False,
                id="clean-db-clean-scrape",
            ),
            pytest.param(
                _RESTAURANT_DESC_NOISY,
                _RESTAURANT_DESC,
                1,
                False,
                id="noisy-db-amount-may-change-same-amount",
            ),
            pytest.param(
                _RESTAURANT_DESC_NOISY,
                _RESTAURANT_DESC,
                1,
                True,
                id="noisy-db-amount-may-change-amount-changed",
            ),
            pytest.param(
                "SOME OTHER MERCHANT",
                _RESTAURANT_DESC,
                0,
                False,
                id="description-mismatch-not-resolved",
            ),
        ],
    )
    def test_resolve_by_description(
        self,
        db_desc: str,
        settle_desc: str,
        expected_resolved: int,
        expected_amount_changed: bool,
    ) -> None:
        """
        GIVEN: A DB pending row and a settled scraped transaction.
        WHEN:  ``_resolve_pending_transactions`` is called.
        THEN:  Rows whose raw_description matches (exactly or via the
               "Amount may change..." prefix) are resolved; mismatches are
               not.  Amount changes are detected correctly.
        """
        db_amount = _RESTAURANT_AMOUNT_V1
        scrape_amount = (
            _RESTAURANT_AMOUNT_V2 if expected_amount_changed else db_amount
        )

        stmt = _make_settled_statement(settle_desc, scrape_amount)
        db_row = _make_pending_db_row(db_desc, db_amount)
        stub = _StubClient([db_row])

        result = _resolve_pending_transactions(
            stmt, _ACCT_ID, stub, user_timezone="UTC"
        )

        assert result.resolved == expected_resolved
        assert (result.resolved_amount_changed > 0) == (
            expected_amount_changed and expected_resolved > 0
        )
        resolve_posts = [p for p in stub.posts if "/resolve-pending/" in p[0]]
        assert len(resolve_posts) == expected_resolved

    ####################################################################
    #
    def test_out_of_date_range_not_resolved(self) -> None:
        """
        GIVEN: A DB pending row whose posted_date is more than 5 days before
               the settled scrape date.
        WHEN:  ``_resolve_pending_transactions`` is called.
        THEN:  No resolution happens (date proximity check rejects it).
        """
        db_row = _make_pending_db_row(
            _STABLE_DESC,
            _STABLE_AMOUNT,
            posted_date="2026-04-01T00:00:00Z",  # 49 days before settle date
        )
        stmt = _make_settled_statement(_STABLE_DESC, _STABLE_AMOUNT)
        stub = _StubClient([db_row])

        result = _resolve_pending_transactions(
            stmt, _ACCT_ID, stub, user_timezone="UTC"
        )

        assert result.resolved == 0

    ####################################################################
    #
    def test_two_settled_one_pending_only_one_resolved(self) -> None:
        """
        GIVEN: Two settled scraped transactions with the same description
               but only one matching DB pending row.
        WHEN:  ``_resolve_pending_transactions`` is called.
        THEN:  Exactly one resolution happens; the second settled tx does
               not double-consume the same pending row.
        """
        tx1 = ParsedTransaction(
            transaction_date=_SETTLE_DATE,
            raw_description=_STABLE_DESC,
            amount=_STABLE_AMOUNT,
            running_balance=Decimal("975.00"),
            transaction_type="purchase",
            pending=False,
        )
        tx2 = ParsedTransaction(
            transaction_date=_SETTLE_DATE,
            raw_description=_STABLE_DESC,
            amount=_STABLE_AMOUNT,
            running_balance=Decimal("950.00"),
            transaction_type="purchase",
            pending=False,
        )
        stmt = ParsedStatement(
            beginning_balance=Decimal("1000.00"),
            beginning_date=_SETTLE_DATE,
            ending_balance=Decimal("950.00"),
            ending_date=_SETTLE_DATE,
            total_credits=Decimal("0"),
            total_debits=Decimal("50.00"),
            transactions=[tx1, tx2],
        )
        db_row = _make_pending_db_row(_STABLE_DESC, _STABLE_AMOUNT)
        stub = _StubClient([db_row])

        result = _resolve_pending_transactions(
            stmt, _ACCT_ID, stub, user_timezone="UTC"
        )

        assert result.resolved == 1


########################################################################
########################################################################
#


def _seed_pending_transaction(
    fake: _FakeClient,
    account_id: str,
    *,
    amount: Decimal,
    desc: str,
) -> dict[str, Any]:
    """Seed a pending transaction into the fake client."""
    tx_id = fake._mint_id("tx")
    row: dict[str, Any] = {
        "id": tx_id,
        "bank_account": account_id,
        "posted_date": "2026-05-17T00:00:00Z",
        "amount": str(amount.quantize(Decimal("0.01"))),
        "raw_description": desc,
        "transaction_type": "purchase",
        "pending": True,
    }
    fake.transactions[tx_id] = row
    return row


########################################################################
########################################################################
#
class TestImportBofaSavedPendingDedup:
    """
    Integration tests for pending-transaction dedup via ``import_bofa_saved``.

    These tests exercise the full pipeline through the CLI:
    ``_get_variable_amount_descs`` -> ``_resolve_pending_transactions`` ->
    ``_filter_existing_pending`` -> ``import_statement``.
    """

    ####################################################################
    #
    def test_stable_pending_not_reimported_on_next_day_scrape(
        self,
        fake_client: _FakeClient,
        tmp_path: Path,
    ) -> None:
        """
        GIVEN: A stable-amount pending transaction already in the DB (imported
               on a previous calendar day, so posted_date differs from today).
        WHEN:  A saved scrape containing the same pending transaction is
               replayed via ``import_bofa_saved``.
        THEN:  No new transaction is POSTed; the existing pending is
               recognised as a duplicate despite the date shift.
        """
        acct = _seed_account(fake_client, last_four="1111")
        _seed_pending_transaction(
            fake_client, acct["id"], desc=_STABLE_DESC, amount=_STABLE_AMOUNT
        )

        scrape_path = tmp_path / "2026-05-18-080000-1111.json"
        _write_scrape_json(
            scrape_path,
            last_four="1111",
            tx_date_str="Processing",
            amount=str(
                _STABLE_AMOUNT
            ),  # negative: BofA stores debits as negative
            desc=_STABLE_DESC,
            ending_balance="1000.00",
            running_balance="1000.00",
        )

        result = _run(str(scrape_path))

        assert result.exit_code == 0, result.output
        new_posts = [
            c
            for c in fake_client.calls
            if c[0] == "POST" and c[1] == "/api/v1/transactions/"
        ]
        assert new_posts == [], (
            f"Expected 0 new tx POSTs, got {len(new_posts)}.\n"
            f"CLI output:\n{result.output}"
        )

    ####################################################################
    #
    @pytest.mark.parametrize(
        "db_desc,scrape_amount_str",
        [
            pytest.param(
                _RESTAURANT_DESC,
                str(abs(_RESTAURANT_AMOUNT_V2)),
                id="clean-db-amount-changed",
            ),
            pytest.param(
                _RESTAURANT_DESC_NOISY,
                str(abs(_RESTAURANT_AMOUNT_V2)),
                id="noisy-db-amount-may-change-amount-changed",
            ),
            pytest.param(
                _RESTAURANT_DESC_NOISY,
                str(abs(_RESTAURANT_AMOUNT_V1)),
                id="noisy-db-amount-may-change-same-amount",
            ),
        ],
    )
    def test_variable_amount_pending_not_reimported(
        self,
        fake_client: _FakeClient,
        tmp_path: Path,
        db_desc: str,
        scrape_amount_str: str,
    ) -> None:
        """
        GIVEN: A restaurant-style pending transaction already in the DB --
               either with the pre-fix noisy description ("Amount may
               change..." appended) or a clean description -- where the
               scraped amount may differ from the DB amount (the merchant's
               final charge isn't settled yet).
        WHEN:  A saved scrape with the clean description and possibly a
               different amount is replayed.
        THEN:  No new transaction is POSTed; "Amount may change..." in the
               description does not break dedup.
        """
        acct = _seed_account(fake_client, last_four="2222")
        _seed_pending_transaction(
            fake_client,
            acct["id"],
            desc=db_desc,
            amount=_RESTAURANT_AMOUNT_V1,
        )

        scrape_path = tmp_path / "2026-05-18-080000-2222.json"
        _write_scrape_json(
            scrape_path,
            last_four="2222",
            tx_date_str="Processing",
            amount=scrape_amount_str,
            desc=_RESTAURANT_RAW,
            ending_balance="1000.00",
            running_balance="1000.00",
        )

        result = _run(str(scrape_path))

        assert result.exit_code == 0, result.output
        new_posts = [
            c
            for c in fake_client.calls
            if c[0] == "POST" and c[1] == "/api/v1/transactions/"
        ]
        assert new_posts == [], (
            f"Expected 0 new tx POSTs, got {len(new_posts)}.\n"
            f"CLI output:\n{result.output}"
        )
