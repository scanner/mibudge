"""Tests for importers.bofa_accounts: config dir, last-4 cache, matching."""

# system imports
import json
import stat
from pathlib import Path
from typing import Any

# 3rd party imports
import pytest
import pytest_check as check
from pytest_mock import MockerFixture

# Project imports
from importers.bofa_accounts import (
    AccountCache,
    CacheChange,
    ambiguous_nicknames,
    bofa_config_dir,
    index_tracked_accounts,
    matches_filters,
    missing_tracked_accounts,
    should_open,
)


########################################################################
########################################################################
#
@pytest.fixture
def cache_path(tmp_path: Path) -> Path:
    """Path of an account cache file inside a not-yet-created dir."""
    return tmp_path / "cfg" / "accounts.json"


########################################################################
########################################################################
#
class TestBofaConfigDir:
    """Tests for bofa_config_dir."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "xdg,expected",
        [
            ("/x/conf", Path("/x/conf/mibudge-bofa-importer")),
            (None, Path("/home/u/.config/mibudge-bofa-importer")),
        ],
    )
    def test_location(
        self, mocker: MockerFixture, xdg: str | None, expected: Path
    ) -> None:
        """
        GIVEN: XDG_CONFIG_HOME set or unset
        WHEN:  bofa_config_dir is called
        THEN:  it is under XDG_CONFIG_HOME, else ~/.config
        """
        env = {"XDG_CONFIG_HOME": xdg} if xdg else {}
        mocker.patch.dict("os.environ", env, clear=True)
        mocker.patch.object(Path, "home", return_value=Path("/home/u"))
        assert bofa_config_dir() == expected


########################################################################
########################################################################
#
class TestAccountCache:
    """Tests for AccountCache load/record/prune/save."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "content",
        [None, "not json", json.dumps({"accounts": ["a"]})],
        ids=["missing", "unparseable", "malformed"],
    )
    def test_load_unusable_file_is_empty(
        self, cache_path: Path, content: str | None
    ) -> None:
        """
        GIVEN: no cache file, or one that cannot be used
        WHEN:  the cache is loaded
        THEN:  it is empty rather than an error
        """
        if content is not None:
            cache_path.parent.mkdir()
            cache_path.write_text(content)
        assert AccountCache.load(cache_path).accounts == {}

    ####################################################################
    #
    def test_save_round_trip_and_mode(self, cache_path: Path) -> None:
        """
        GIVEN: a cache with one recorded account
        WHEN:  it is saved and loaded again
        THEN:  the mapping survives and the file is mode 0600
        """
        cache = AccountCache(cache_path)
        cache.record("Adv Plus", "1234")
        check.is_true(cache.save(), "writes a changed cache")
        check.equal(
            AccountCache.load(cache_path).accounts, {"Adv Plus": "1234"}
        )
        check.equal(stat.S_IMODE(cache_path.stat().st_mode), 0o600)

    ####################################################################
    #
    def test_unchanged_cache_is_not_written(self, cache_path: Path) -> None:
        """
        GIVEN: a cache whose recorded digits match what it holds
        WHEN:  it is saved
        THEN:  nothing is written
        """
        cache = AccountCache(cache_path, {"Adv Plus": "1234"})
        check.is_none(cache.record("Adv Plus", "1234"))
        check.is_false(cache.save())
        check.is_false(cache_path.exists())

    ####################################################################
    #
    def test_record_and_prune_report_changes(self, cache_path: Path) -> None:
        """
        GIVEN: a cache with two nicknames
        WHEN:  one is corrected, one added, and a stale one pruned
        THEN:  every change is recorded in order
        """
        cache = AccountCache(cache_path, {"Old": "1111", "Checking": "2222"})
        cache.record("Checking", "3333")
        cache.record("Savings", "4444")
        cache.prune(["Checking", "Savings"])
        assert cache.changes == [
            CacheChange("Checking", "2222", "3333"),
            CacheChange("Savings", None, "4444"),
            CacheChange("Old", "1111", None),
        ]


########################################################################
########################################################################
#
class TestMatching:
    """Tests for the open/match decisions."""

    ####################################################################
    #
    def test_ambiguous_nicknames(self) -> None:
        """
        GIVEN: overview nicknames with one repeated
        WHEN:  ambiguous_nicknames is called
        THEN:  only the repeated one is returned
        """
        assert ambiguous_nicknames(["A", "B", "A"]) == {"A"}

    ####################################################################
    #
    @pytest.mark.parametrize(
        "filters,last_four,expected",
        [
            ((), None, True),
            (("check",), None, True),
            (("1234",), "1234", True),
            (("1234",), None, False),
            (("savings",), "9999", False),
        ],
    )
    def test_matches_filters(
        self, filters: tuple[str, ...], last_four: str | None, expected: bool
    ) -> None:
        """
        GIVEN: --account filters and an account's nickname/last-4
        WHEN:  matches_filters is called
        THEN:  nickname substrings (any case) and last-4 digits match
        """
        assert matches_filters("Adv Checking", last_four, filters) is expected

    ####################################################################
    #
    @pytest.mark.parametrize(
        "cached,tracked,filters,check_all,expected",
        [
            (None, {"1234"}, (), False, True),
            ("9999", {"1234"}, (), False, False),
            ("1234", {"1234"}, (), False, True),
            ("9999", {"1234"}, (), True, True),
            ("9999", None, (), False, True),
            ("1234", {"1234"}, ("savings",), False, False),
        ],
        ids=[
            "unknown-opens",
            "cached-untracked-skips",
            "cached-tracked-opens",
            "check-all-opens",
            "save-only-opens",
            "filtered-out-skips",
        ],
    )
    def test_should_open(
        self,
        cached: str | None,
        tracked: set[str] | None,
        filters: tuple[str, ...],
        check_all: bool,
        expected: bool,
    ) -> None:
        """
        GIVEN: what the cache knows, the tracked set, filters, check-all
        WHEN:  should_open is called
        THEN:  only accounts that could be imported are opened
        """
        assert (
            should_open("Adv Checking", cached, tracked, filters, check_all)
            is expected
        )


########################################################################
########################################################################
#
class TestTrackedAccounts:
    """Tests for index_tracked_accounts and missing_tracked_accounts."""

    ####################################################################
    #
    @pytest.fixture
    def mibudge_rows(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Bank accounts at BofA and elsewhere, two sharing a last-4."""
        banks = [
            {"id": "b-bofa", "name": "Bank of America"},
            {"id": "b-other", "name": "Credit Union"},
        ]
        accounts: list[dict[str, Any]] = [
            {"id": "a1", "name": "Checking", "bank": "b-bofa",
             "account_number": "000011112222"},
            {"id": "a2", "name": "Savings", "bank": "b-bofa",
             "account_number": "0000333344445555"},
            {"id": "a3", "name": "Joint", "bank": "b-bofa",
             "account_number": "999944445555"},
            {"id": "a4", "name": "CU", "bank": "b-other",
             "account_number": "77772222"},
            {"id": "a5", "name": "No number", "bank": "b-bofa",
             "account_number": None},
        ]  # fmt: skip
        return accounts, banks

    ####################################################################
    #
    def test_index(
        self, mibudge_rows: tuple[list[dict[str, Any]], list[dict[str, Any]]]
    ) -> None:
        """
        GIVEN: mibudge accounts at BofA and another bank
        WHEN:  they are indexed for bank name 'bank of america'
        THEN:  only BofA accounts are tracked, shared last-4s are ambiguous
        """
        accounts, banks = mibudge_rows
        tracked, ambiguous = index_tracked_accounts(
            accounts, banks, "bank of america"
        )
        check.equal({k: v["id"] for k, v in tracked.items()}, {"2222": "a1"})
        check.equal(
            {k: [a["id"] for a in v] for k, v in ambiguous.items()},
            {"5555": ["a2", "a3"]},
        )

    ####################################################################
    #
    def test_missing(self) -> None:
        """
        GIVEN: two tracked accounts, one found this run
        WHEN:  missing_tracked_accounts is called
        THEN:  the other one is returned
        """
        tracked = {"1111": {"name": "A"}, "2222": {"name": "B"}}
        assert missing_tracked_accounts(tracked, ["1111"]) == [{"name": "B"}]
