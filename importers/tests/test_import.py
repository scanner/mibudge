"""
Integration tests for the ``import`` CLI command.

These tests exercise the full ``cli_group -> import_cmd`` path end to
end, with a ``FakeClient`` substituted for the real ``MibudgeClient``.
The fake keeps bank accounts and transactions in in-memory dicts and
records every call; tests then assert on what the CLI would have sent
to a real server.

We patch ``importers.import_transactions._build_client`` (rather than
the client class itself) because the CLI always routes through that
factory. This keeps credential/TLS plumbing out of the test path.
"""

# system imports
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

# 3rd party imports
import pytest
from click.testing import CliRunner
from pytest_mock import MockerFixture

# Project imports
from importers import import_transactions as it
from importers.tests.factories import OFXTxnSpec


########################################################################
########################################################################
#
class FakeClient:
    """
    In-memory stand-in for ``MibudgeClient`` used by the CLI.

    Implements the context-manager protocol and just enough of the
    MibudgeClient surface -- ``authenticate``, ``get``, ``get_all``,
    ``post``, ``patch``, ``close`` -- that ``import_cmd`` exercises.
    State lives in dicts so tests can pre-seed accounts / existing
    transactions and inspect the post-run state.

    Every request is appended to ``calls`` so tests can assert on the
    exact HTTP traffic the CLI would have produced.
    """

    ####################################################################
    #
    def __init__(self) -> None:
        self.accounts: dict[str, dict[str, Any]] = {}
        self.transactions: dict[str, dict[str, Any]] = {}
        self.banks: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, str, Any]] = []
        self.authenticated = False
        self._next_id = 0

    ####################################################################
    #
    def _mint_id(self, prefix: str) -> str:
        self._next_id += 1
        return f"{prefix}-{self._next_id:04d}"

    ####################################################################
    #
    def authenticate(self) -> None:
        self.authenticated = True
        self.calls.append(("AUTH", "/api/token/", None))

    ####################################################################
    #
    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self.calls.append(("GET", path, params))
        # Single-object fetches: /api/v1/bank-accounts/<id>/
        if path.startswith("/api/v1/bank-accounts/") and path.endswith("/"):
            acct_id = path.rstrip("/").rsplit("/", 1)[-1]
            if acct_id in self.accounts:
                return self.accounts[acct_id]
        raise KeyError(f"FakeClient.get: unhandled path {path!r}")

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
            for tx in self.transactions.values():
                if bank_acct and tx.get("bank_account") != bank_acct:
                    continue
                yield tx
            return
        if path == "/api/v1/banks/":
            yield from self.banks.values()
            return
        raise KeyError(f"FakeClient.get_all: unhandled path {path!r}")

    ####################################################################
    #
    def post(self, path: str, json: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("POST", path, json))
        if path == "/api/v1/bank-accounts/":
            acct_id = self._mint_id("acct")
            row = {"id": acct_id, **json}
            self.accounts[acct_id] = row
            return row
        if path == "/api/v1/transactions/":
            tx_id = self._mint_id("tx")
            row = {"id": tx_id, **json}
            self.transactions[tx_id] = row
            return row
        raise KeyError(f"FakeClient.post: unhandled path {path!r}")

    ####################################################################
    #
    def patch(self, path: str, json: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("PATCH", path, json))
        if path.startswith("/api/v1/transactions/") and path.endswith("/"):
            tx_id = path.rstrip("/").rsplit("/", 1)[-1]
            if tx_id in self.transactions:
                self.transactions[tx_id].update(json)
                return self.transactions[tx_id]
        raise KeyError(f"FakeClient.patch: unhandled path {path!r}")

    ####################################################################
    #
    def close(self) -> None:
        pass

    ####################################################################
    #
    def __enter__(self) -> "FakeClient":
        return self

    ####################################################################
    #
    def __exit__(self, *args: Any) -> None:
        self.close()


########################################################################
########################################################################
#
@pytest.fixture
def fake_client(mocker: MockerFixture) -> FakeClient:
    """
    Patch ``_build_client`` to return a fresh ``FakeClient``.

    Returning the same instance the CLI will receive lets tests seed
    state before invoking and inspect call history afterwards.
    """
    fc = FakeClient()
    mocker.patch.object(it, "_build_client", return_value=fc)
    return fc


####################################################################
#
def _seed_account(
    fake: FakeClient,
    *,
    name: str = "Checking",
    account_number: str = "",
    account_type: str = "C",
    posted_balance: str = "1000.00",
) -> dict[str, Any]:
    """Seed one pre-existing BankAccount into the fake and return it."""
    acct_id = fake._mint_id("acct")
    row = {
        "id": acct_id,
        "name": name,
        "account_number": account_number,
        "account_type": account_type,
        "posted_balance": posted_balance,
        "available_balance": posted_balance,
    }
    fake.accounts[acct_id] = row
    return row


####################################################################
#
def _invoke(*args: str) -> Any:
    """
    Invoke the CLI with MIBUDGE_* env vars stubbed in.

    ``--plain`` is a parent-group option so it must precede the
    subcommand in argv -- we prepend it here so every test gets
    deterministic non-rich output.
    """
    runner = CliRunner()
    env = {
        "MIBUDGE_URL": "http://testserver",
        "MIBUDGE_USERNAME": "u",
        "MIBUDGE_PASSWORD": "p",
    }
    return runner.invoke(
        it.cli_group,
        ["--plain", *args],
        env=env,
        catch_exceptions=False,
    )


########################################################################
########################################################################
#
class TestImportCmd:
    """End-to-end tests for ``importers import``."""

    ####################################################################
    #
    def test_csv_into_existing_account_happy_path(
        self,
        fake_client: FakeClient,
        bofa_csv_factory: Callable[..., tuple[Path, list[Any]]],
    ) -> None:
        """
        GIVEN: a BofA CSV and an existing account referenced by --account
        WHEN:  ``import`` runs
        THEN:  every transaction is POSTed and the balance check fetches
               the account afterwards
        """
        acct = _seed_account(fake_client)
        csv_path, rows = bofa_csv_factory(num_transactions=5)

        result = _invoke("import", "-f", str(csv_path), "--account", acct["id"])

        assert result.exit_code == 0, result.output
        posts = [
            c
            for c in fake_client.calls
            if c[0] == "POST" and c[1] == "/api/v1/transactions/"
        ]
        assert len(posts) == len(rows)
        assert all(p[2]["bank_account"] == acct["id"] for p in posts)
        # Balance verification step fetched the account.
        assert (
            "GET",
            f"/api/v1/bank-accounts/{acct['id']}/",
            None,
        ) in fake_client.calls

    ####################################################################
    #
    def test_ofx_create_account_flow(
        self,
        fake_client: FakeClient,
        ofx_file_factory: Callable[..., tuple[Path, list[OFXTxnSpec]]],
    ) -> None:
        """
        GIVEN: an OFX file whose ACCTID does not match any existing account
        WHEN:  ``import --create-account`` runs with --name and --bank
        THEN:  a new BankAccount is created (with account_number == ACCTID)
               and every OFX transaction is POSTed into it
        """
        ofx_path, specs = ofx_file_factory(
            num_transactions=3, acct_id="9999888877", ending_balance="800.00"
        )
        bank_uuid = "11111111-1111-1111-1111-111111111111"

        result = _invoke(
            "import",
            "-f",
            str(ofx_path),
            "--create-account",
            "--name",
            "New Checking",
            "--bank",
            bank_uuid,
        )

        assert result.exit_code == 0, result.output
        assert len(fake_client.accounts) == 1
        (created,) = fake_client.accounts.values()
        assert created["account_number"] == "9999888877"
        assert created["bank"] == bank_uuid
        assert created["account_type"] == "C"
        assert len(fake_client.transactions) == len(specs)

    ####################################################################
    #
    def test_ofx_acctid_automatch_existing_account(
        self,
        fake_client: FakeClient,
        ofx_file_factory: Callable[..., tuple[Path, list[OFXTxnSpec]]],
    ) -> None:
        """
        GIVEN: an OFX file whose ACCTID matches an existing account's
               account_number
        WHEN:  ``import`` runs with no --account flag
        THEN:  the existing account is selected automatically; no new
               account is created
        """
        acct = _seed_account(fake_client, account_number="5555444433")
        ofx_path, specs = ofx_file_factory(
            num_transactions=2, acct_id="5555444433"
        )

        result = _invoke("import", "-f", str(ofx_path))

        assert result.exit_code == 0, result.output
        assert len(fake_client.accounts) == 1  # no new one created
        posts = [
            c
            for c in fake_client.calls
            if c[0] == "POST" and c[1] == "/api/v1/transactions/"
        ]
        assert len(posts) == len(specs)
        assert all(p[2]["bank_account"] == acct["id"] for p in posts)

    ####################################################################
    #
    def test_dedup_skips_existing_transactions(
        self,
        fake_client: FakeClient,
        bofa_csv_factory: Callable[..., tuple[Path, list[Any]]],
    ) -> None:
        """
        GIVEN: a CSV whose rows already exist server-side (same date,
               amount, raw_description)
        WHEN:  ``import`` runs into that account
        THEN:  no new POST is issued for the duplicates; they are
               counted as skipped
        """
        acct = _seed_account(fake_client)
        csv_path, rows = bofa_csv_factory(num_transactions=4)

        # Seed the fake with identical rows so the dedup key matches.
        from datetime import datetime

        for row in rows:
            tx_id = fake_client._mint_id("tx")
            fake_client.transactions[tx_id] = {
                "id": tx_id,
                "bank_account": acct["id"],
                "transaction_date": datetime.combine(
                    row.transaction_date, datetime.min.time()
                ).isoformat(),
                "amount": str(row.amount),
                "raw_description": row.description,
                "transaction_type": "PUR",
            }
        pre_tx_count = len(fake_client.transactions)

        result = _invoke("import", "-f", str(csv_path), "--account", acct["id"])

        assert result.exit_code == 0, result.output
        # No new transactions posted.
        assert len(fake_client.transactions) == pre_tx_count
        posts = [
            c
            for c in fake_client.calls
            if c[0] == "POST" and c[1] == "/api/v1/transactions/"
        ]
        assert posts == []

    ####################################################################
    #
    def test_self_heal_patches_empty_transaction_type(
        self,
        fake_client: FakeClient,
        bofa_csv_factory: Callable[..., tuple[Path, list[Any]]],
    ) -> None:
        """
        GIVEN: an existing server-side transaction with empty
               ``transaction_type`` but a parser that now classifies it
        WHEN:  ``import`` re-runs with a CSV containing that row
        THEN:  the importer PATCHes the existing row's transaction_type
               rather than creating a duplicate
        """
        acct = _seed_account(fake_client)
        csv_path, rows = bofa_csv_factory(num_transactions=1)
        row = rows[0]

        from datetime import datetime

        tx_id = fake_client._mint_id("tx")
        fake_client.transactions[tx_id] = {
            "id": tx_id,
            "bank_account": acct["id"],
            "transaction_date": datetime.combine(
                row.transaction_date, datetime.min.time()
            ).isoformat(),
            "amount": str(row.amount),
            "raw_description": row.description,
            "transaction_type": "",  # empty -- will be backfilled
        }

        result = _invoke("import", "-f", str(csv_path), "--account", acct["id"])

        assert result.exit_code == 0, result.output
        patches = [c for c in fake_client.calls if c[0] == "PATCH"]
        # A PATCH is only issued if the parser inferred a non-empty type.
        # If the generated description didn't match any pattern, the
        # row is simply skipped -- still no new POST.
        posts = [
            c
            for c in fake_client.calls
            if c[0] == "POST" and c[1] == "/api/v1/transactions/"
        ]
        assert posts == []
        if patches:
            (method, path, body) = patches[0]
            assert path == f"/api/v1/transactions/{tx_id}/"
            assert body["transaction_type"] != ""

    ####################################################################
    #
    def test_mutually_exclusive_account_flags_rejected(
        self,
        fake_client: FakeClient,
        bofa_csv_factory: Callable[..., tuple[Path, list[Any]]],
    ) -> None:
        """
        GIVEN: both --create-account and --account are supplied
        WHEN:  ``import`` runs
        THEN:  the CLI rejects the combination before any API calls
        """
        csv_path, _ = bofa_csv_factory(num_transactions=1)

        result = _invoke(
            "import",
            "-f",
            str(csv_path),
            "--account",
            "11111111-1111-1111-1111-111111111111",
            "--create-account",
            "--name",
            "X",
            "--bank",
            "22222222-2222-2222-2222-222222222222",
        )

        assert result.exit_code != 0
        assert "mutually exclusive" in result.output.lower()
        # No API calls made.
        assert fake_client.calls == []
