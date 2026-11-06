"""
Tests for the live BofA importer's account loop and saved scrapes.

The BofA side is a fake scraper injected as the `bofa_scraper` module
(with a stand-in `selenium.common.exceptions`), so these run without
the optional importers-bofa group.  The mibudge side is a fake client
returned from a patched `_build_client`.
"""

# system imports
import json
import os
import sys
import types
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 3rd party imports
import pytest
import pytest_check as check
from click.testing import CliRunner, Result
from pytest_mock import MockerFixture

# Project imports
from importers import import_bofa_live as live
from importers.bofa_accounts import AccountCache
from importers.import_bofa_saved import _ReplayAccount
from importers.tests.factories import FakeStore

BANKS = [
    {"id": "b-bofa", "name": "Bank of America"},
    {"id": "b-other", "name": "Credit Union"},
]
TRACKED_ACCOUNTS = [
    {"id": "a-chk", "name": "Checking", "bank": "b-bofa",
     "account_number": "000011111234"},
    {"id": "a-sav", "name": "Savings", "bank": "b-bofa",
     "account_number": "000022225678"},
    {"id": "a-cu", "name": "CU", "bank": "b-other",
     "account_number": "33339999"},
]  # fmt: skip


########################################################################
########################################################################
#
class NoSuchElementException(Exception):
    """Stand-in for selenium's NoSuchElementException."""


class WebDriverException(Exception):
    """Stand-in for selenium's WebDriverException."""


########################################################################
########################################################################
#
@dataclass
class FakeTxn:
    """Just enough of a bofa_scraper Transaction."""

    date: str = "10/01/2026"
    desc: str = "COFFEE"
    amount: float = -4.5
    type: str = "Debit Card"
    running_balance: float = 95.5
    txn_hash: str = "h"


########################################################################
########################################################################
#
class FakeAccount:
    """A bofa_scraper Account: nickname now, last-4 once opened."""

    def __init__(self, nickname: str, page_last_four: str | None):
        self.nickname = nickname
        self.page_last_four = page_last_four
        self.last_four: str | None = None
        self.transactions: list[FakeTxn] = []

    def get_name(self) -> str:
        return self.nickname

    def get_balance(self) -> float:
        return 95.5

    def get_last_four(self) -> str | None:
        return self.last_four

    def get_transactions(self) -> list[FakeTxn]:
        return self.transactions


########################################################################
########################################################################
#
class FakeSession:
    """A bofa_scraper ScrapeSession over a FakeAccount."""

    def __init__(self, account: FakeAccount, bofa: "FakeBofA"):
        self.account = account
        self.bofa = bofa
        account.last_four = account.page_last_four

    def get_last_four(self) -> str | None:
        return self.account.last_four

    def scrape_transactions(self) -> "FakeSession":
        self.bofa.scrapes += 1
        if self.bofa.scrapes == 2 and self.bofa.second_scrape_error:
            raise self.bofa.second_scrape_error
        self.account.transactions = [FakeTxn()]
        return self

    def load_more_transactions(self) -> "FakeSession":
        if not self.bofa.view_more:
            raise NoSuchElementException()
        return self

    def close(self) -> None:
        pass


########################################################################
########################################################################
#
@dataclass
class FakeBofA:
    """The overview tiles a run sees, and which ones it opened."""

    tiles: list[tuple[str, str | None]] = field(default_factory=list)
    opened: list[str] = field(default_factory=list)
    login: tuple[str, str] | None = None
    view_more: bool = False
    second_scrape_error: Exception | None = None
    scrapes: int = 0

    def scraper_class(self) -> type:
        bofa = self

        class FakeScraper:
            logged_in = False

            def __init__(self, bofa_id: str, passcode: str, **kwargs: Any):
                bofa.login = (bofa_id, passcode)

            def login(self) -> None:
                self.logged_in = True

            def get_accounts(self) -> list[FakeAccount]:
                return [FakeAccount(n, l4) for n, l4 in bofa.tiles]

            def open_account(self, account: FakeAccount) -> FakeSession:
                bofa.opened.append(account.get_name())
                return FakeSession(account, bofa)

            def quit(self) -> None:
                pass

        return FakeScraper


########################################################################
########################################################################
#
class FakeClient:
    """mibudge API client recording sync-scrape POSTs."""

    def __init__(self) -> None:
        self.synced: list[str] = []

    def __enter__(self) -> "FakeClient":
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def authenticate(self) -> None:
        pass

    def get(self, path: str) -> dict[str, Any]:
        return {"timezone": "America/Los_Angeles"}

    def get_all(self, path: str, params: Any = None) -> list[dict[str, Any]]:
        return {
            "/api/v1/bank-accounts/": TRACKED_ACCOUNTS,
            "/api/v1/banks/": BANKS,
        }[path]

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.synced.append(path.split("/")[4])
        return {
            "deleted_pending": 0,
            "inserted_posted": 1,
            "skipped_posted": 0,
            "inserted_pending": 0,
            "balance_mismatch": None,
            "details_needed": [],
        }


########################################################################
########################################################################
#
@pytest.fixture
def fake_bofa(mocker: MockerFixture) -> FakeBofA:
    """Install a fake `bofa_scraper` (and selenium exceptions) module."""
    bofa = FakeBofA()
    exceptions = types.ModuleType("selenium.common.exceptions")
    exceptions.NoSuchElementException = NoSuchElementException  # type: ignore[attr-defined]
    exceptions.WebDriverException = WebDriverException  # type: ignore[attr-defined]
    scraper_mod = types.ModuleType("bofa_scraper")
    scraper_mod.BofAScraper = bofa.scraper_class()  # type: ignore[attr-defined]
    mocker.patch.dict(
        sys.modules,
        {
            "bofa_scraper": scraper_mod,
            "selenium": types.ModuleType("selenium"),
            "selenium.common": types.ModuleType("selenium.common"),
            "selenium.common.exceptions": exceptions,
        },
    )
    return bofa


########################################################################
########################################################################
#
@pytest.fixture
def fake_client(mocker: MockerFixture) -> FakeClient:
    """Patch `_build_client` to return a FakeClient."""
    fc = FakeClient()
    mocker.patch.object(live, "_build_client", return_value=fc)
    return fc


########################################################################
########################################################################
#
@pytest.fixture
def cache_path(tmp_path: Path) -> Path:
    """Account cache file path for a run."""
    return tmp_path / "accounts.json"


########################################################################
########################################################################
#
@pytest.fixture
def seed_cache(cache_path: Path) -> Callable[[dict[str, str]], None]:
    """Return a function that writes the account cache before a run."""

    def _seed(accounts: dict[str, str]) -> None:
        cache_path.write_text(
            json.dumps({"format_version": 1, "accounts": accounts})
        )

    return _seed


########################################################################
########################################################################
#
@pytest.fixture
def run_live(
    mocker: MockerFixture,
    tmp_path: Path,
    cache_path: Path,
    fake_client: FakeClient,
) -> Callable[..., Result]:
    """Return a function that runs the live importer CLI in plain mode.

    `login` replaces the default --bofa-id / --bofa-passcode flags and
    `input` answers prompts.

    BOFA_* and MIBUDGE_* variables from the developer's environment are
    removed, and XDG_CONFIG_HOME points into tmp_path, so neither they
    nor the developer's config file can steer option resolution.
    """
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("BOFA_", "MIBUDGE_"))
    }
    env["XDG_CONFIG_HOME"] = str(tmp_path / "xdg")
    mocker.patch.dict(os.environ, env, clear=True)

    def _run(
        *args: str,
        login: tuple[str, ...] = ("--bofa-id", "id", "--bofa-passcode", "pw"),
        input: str | None = None,
    ) -> Result:
        return CliRunner().invoke(
            live.cli_cmd,
            [
                "--plain",
                *login,
                "--details-limit",
                "0",
                "--account-cache",
                str(cache_path),
                *args,
            ],
            input=input,
            catch_exceptions=False,
        )

    return _run


########################################################################
########################################################################
#
class TestBofaLogin:
    """Tests for where the BofA login comes from."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "login,fields,input,expected",
        [
            pytest.param(
                (),
                {"username": "store-id", "password": "store-pw"},
                None,
                ("store-id", "store-pw"),
                id="store",
            ),
            pytest.param(
                ("--bofa-id", "flag-id"),
                {"username": "store-id", "password": "store-pw"},
                None,
                ("flag-id", "store-pw"),
                id="flag-wins",
            ),
            pytest.param(
                (),
                {"username": "store-id"},
                "typed-pw\n",
                ("store-id", "typed-pw"),
                id="prompt-for-missing",
            ),
        ],
    )
    def test_flags_then_store_then_prompt(
        self,
        fake_bofa: FakeBofA,
        fake_client: FakeClient,
        run_live: Callable[..., Result],
        creds_store: Callable[..., FakeStore],
        login: tuple[str, ...],
        fields: dict[str, str],
        input: str | None,
        expected: tuple[str, str],
    ) -> None:
        """
        GIVEN: a --bofa-creds-url store, with or without a flag, and
               with or without a password field
        WHEN:  the importer runs
        THEN:  a flag wins, then the store's field, then a prompt
        """
        fake_bofa.tiles = [("Main", "1234")]
        store = creds_store(**fields)

        result = run_live(
            "--bofa-creds-url", store.url, login=login, input=input
        )

        check.equal(result.exit_code, 0, result.output)
        check.equal(fake_bofa.login, expected)


########################################################################
########################################################################
#
class TestAccountLoop:
    """Tests for matching BofA accounts to mibudge accounts."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "view_more,second_scrape_error,exit_code,synced,scrapes",
        [
            pytest.param(False, None, 0, ["a-chk"], 1, id="no-view-more"),
            pytest.param(True, None, 0, ["a-chk"], 2, id="view-more"),
            pytest.param(
                True,
                NoSuchElementException("no amount-cell"),
                1,
                [],
                2,
                id="second-scrape-missing-cell",
            ),
        ],
    )
    def test_view_more_and_second_scrape(
        self,
        fake_bofa: FakeBofA,
        fake_client: FakeClient,
        run_live: Callable[..., Result],
        view_more: bool,
        second_scrape_error: Exception | None,
        exit_code: int,
        synced: list[str],
        scrapes: int,
    ) -> None:
        """
        GIVEN: a tracked tile with or without a "View more" button, and
               a second scrape that succeeds or hits a missing cell
        WHEN:  the importer runs
        THEN:  only a missing button falls back to the first scrape's
               rows; a missing cell fails the bank account unsynced
        """
        fake_bofa.tiles = [("Main", "1234")]
        fake_bofa.view_more = view_more
        fake_bofa.second_scrape_error = second_scrape_error
        result = run_live()
        check.equal(result.exit_code, exit_code, result.output)
        check.equal(fake_client.synced, synced, "bank accounts synced")
        check.equal(fake_bofa.scrapes, scrapes, "scrapes run")

    ####################################################################
    #
    def test_empty_cache_opens_all_and_records(
        self,
        fake_bofa: FakeBofA,
        fake_client: FakeClient,
        run_live: Callable[..., Result],
        cache_path: Path,
    ) -> None:
        """
        GIVEN: no cache, two tracked tiles and one untracked tile
        WHEN:  the importer runs
        THEN:  every tile is opened, tracked ones synced, the untracked
               one skipped without failing, and all three cached
        """
        fake_bofa.tiles = [
            ("Main", "1234"),
            ("Kids", "4321"),
            ("Rainy", "5678"),
        ]
        result = run_live()
        check.equal(result.exit_code, 0, result.output)
        check.equal(fake_bofa.opened, ["Main", "Kids", "Rainy"])
        check.equal(fake_client.synced, ["a-chk", "a-sav"])
        check.equal(
            AccountCache.load(cache_path).accounts,
            {"Main": "1234", "Kids": "4321", "Rainy": "5678"},
        )

    ####################################################################
    #
    def test_cached_untracked_account_is_not_opened(
        self,
        fake_bofa: FakeBofA,
        fake_client: FakeClient,
        run_live: Callable[..., Result],
        seed_cache: Callable[[dict[str, str]], None],
    ) -> None:
        """
        GIVEN: a cache that knows every tile, one of them untracked
        WHEN:  the importer runs
        THEN:  the untracked tile is never opened
        """
        seed_cache({"Main": "1234", "Kids": "4321", "Rainy": "5678"})
        fake_bofa.tiles = [
            ("Main", "1234"),
            ("Kids", "4321"),
            ("Rainy", "5678"),
        ]
        result = run_live()
        check.equal(result.exit_code, 0, result.output)
        check.equal(fake_bofa.opened, ["Main", "Rainy"])
        check.equal(fake_client.synced, ["a-chk", "a-sav"])

    ####################################################################
    #
    def test_opened_account_corrects_cache(
        self,
        caplog: pytest.LogCaptureFixture,
        fake_bofa: FakeBofA,
        fake_client: FakeClient,
        run_live: Callable[..., Result],
        seed_cache: Callable[[dict[str, str]], None],
        cache_path: Path,
    ) -> None:
        """
        GIVEN: a cache claiming a nickname holds tracked digits it no
               longer holds
        WHEN:  the importer opens it
        THEN:  the cache is corrected to what the page shows
        """
        seed_cache({"Main": "1234", "Rainy": "5678"})
        fake_bofa.tiles = [("Main", "4321"), ("Rainy", "5678")]
        run_live()
        check.equal(fake_client.synced, ["a-sav"])
        check.equal(AccountCache.load(cache_path).get("Main"), "4321")
        check.is_in("Account cache: changed 'Main': 1234 -> 4321", caplog.text)

    ####################################################################
    #
    def test_stale_cache_warns_then_check_all_rebuilds(
        self,
        caplog: pytest.LogCaptureFixture,
        fake_bofa: FakeBofA,
        fake_client: FakeClient,
        run_live: Callable[..., Result],
        seed_cache: Callable[[dict[str, str]], None],
        cache_path: Path,
    ) -> None:
        """
        GIVEN: a cache that wrongly marks the tracked account's tile as
               untracked, plus an entry for a tile that is gone
        WHEN:  the importer runs, then runs with --check-all-accounts
        THEN:  the first run warns the account is missing; the second
               imports it, corrects the cache, and prunes the gone tile
        """
        seed_cache({"Main": "4321", "Rainy": "5678", "Gone": "0000"})
        fake_bofa.tiles = [("Main", "1234"), ("Rainy", "5678")]

        run_live()
        check.equal(fake_client.synced, ["a-sav"])
        check.is_in("not found on BofA: 'Checking' (1234)", caplog.text)
        check.is_in("re-run with --check-all-accounts", caplog.text)

        fake_client.synced.clear()
        caplog.clear()
        second = run_live("--check-all-accounts")
        check.equal(second.exit_code, 0, second.output)
        check.equal(fake_client.synced, ["a-chk", "a-sav"])
        check.is_not_in("not found on BofA", caplog.text)
        check.equal(
            AccountCache.load(cache_path).accounts,
            {"Main": "1234", "Rainy": "5678"},
        )

    ####################################################################
    #
    def test_account_filter_matches_last_four(
        self,
        caplog: pytest.LogCaptureFixture,
        fake_bofa: FakeBofA,
        fake_client: FakeClient,
        run_live: Callable[..., Result],
    ) -> None:
        """
        GIVEN: two tracked tiles and no cache
        WHEN:  the importer runs with --account 5678
        THEN:  only the account whose page shows 5678 is synced, and no
               missing-account warning is given for the other
        """
        fake_bofa.tiles = [("Main", "1234"), ("Rainy", "5678")]
        result = run_live("--account", "5678")
        check.equal(result.exit_code, 0, result.output)
        check.equal(fake_client.synced, ["a-sav"])
        check.is_not_in("not found on BofA", caplog.text)

    ####################################################################
    #
    def test_duplicate_nicknames_are_not_cached(
        self,
        fake_bofa: FakeBofA,
        run_live: Callable[..., Result],
        cache_path: Path,
    ) -> None:
        """
        GIVEN: two overview tiles sharing a nickname
        WHEN:  the importer runs
        THEN:  both are opened and neither is cached
        """
        fake_bofa.tiles = [("Card", "1234"), ("Card", "5678")]
        run_live()
        check.equal(fake_bofa.opened, ["Card", "Card"])
        check.equal(AccountCache.load(cache_path).accounts, {})


########################################################################
########################################################################
#
class TestSavedScrape:
    """Tests for saving and replaying scrapes with last_four."""

    ####################################################################
    #
    def test_save_only_records_last_four(
        self,
        fake_bofa: FakeBofA,
        run_live: Callable[..., Result],
        tmp_path: Path,
    ) -> None:
        """
        GIVEN: a tile whose page shows last-4 1234
        WHEN:  the importer runs with --save-only
        THEN:  the file is named for and carries last_four
        """
        fake_bofa.tiles = [("Main", "1234")]
        save_dir = tmp_path / "saved"
        result = run_live("--save-only", "--save-dir", str(save_dir))
        check.equal(result.exit_code, 0, result.output)
        (saved_file,) = save_dir.glob("*-1234.json")
        saved = live.load_saved_scrape(saved_file)
        check.equal(saved.last_four, "1234")
        check.equal(saved.account_name, "Main")

    ####################################################################
    #
    def test_load_pre_v4_file_has_no_last_four(self, tmp_path: Path) -> None:
        """
        GIVEN: a format_version 3 file, digits only in account_name
        WHEN:  it is loaded
        THEN:  last_four is None and the name still yields the digits
        """
        path = tmp_path / "old.json"
        path.write_text(
            json.dumps(
                {
                    "format_version": 3,
                    "scraped_at": "2026-10-01T00:00:00+00:00",
                    "account_name": "Adv Plus - 1234",
                    "ending_balance": "1.00",
                    "transactions": [],
                }
            )
        )
        saved = live.load_saved_scrape(path)
        check.is_none(saved.last_four)
        check.equal(
            live._extract_last_four(_ReplayAccount(saved).get_name()), "1234"
        )
