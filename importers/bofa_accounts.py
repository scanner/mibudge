"""
BofA account identity for the importers: config dir, last-4 cache, matching.

BofA's account overview shows only each account's nickname.  The last
four digits of the account number -- what a mibudge BankAccount is
matched on -- appear only after the account is opened
(`ScrapeSession.get_last_four()`).  Opening every account on every run
costs page loads against BofA, so the importer keeps a nickname ->
last-4 cache in its config directory:

* An account whose nickname is cached with digits no tracked mibudge
  account has is skipped without opening it.
* An unknown nickname (new account, renamed account, or a nickname
  that more than one overview tile uses) is opened and recorded.
* Whenever an opened account's digits disagree with the cache, the
  cache is corrected.
* `--check-all-accounts` opens every account and rebuilds the cache.

The config directory (`bofa_config_dir()`) is shared by the BofA
importers and is meant to be synced across machines, so a run on one
machine benefits from what another learned.
"""

# system imports
import json
import logging
import os
import tempfile
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CONFIG_DIR_NAME = "mibudge-bofa-importer"
ACCOUNT_CACHE_NAME = "accounts.json"
ACCOUNT_CACHE_FORMAT_VERSION = 1
DEFAULT_BANK_NAME = "Bank of America"


####################################################################
#
def bofa_config_dir() -> Path:
    """Return the BofA importers' config directory.

    `$XDG_CONFIG_HOME/mibudge-bofa-importer`, falling back to
    `~/.config/mibudge-bofa-importer`.  Not created here.
    """
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / CONFIG_DIR_NAME


####################################################################
#
def default_account_cache_path() -> Path:
    """Return the default path of the nickname -> last-4 cache file."""
    return bofa_config_dir() / ACCOUNT_CACHE_NAME


########################################################################
########################################################################
#
@dataclass(frozen=True)
class CacheChange:
    """One change to the account cache, for the end-of-run report.

    `old` is None for an added nickname; `new` is None for a removed
    one.
    """

    nickname: str
    old: str | None
    new: str | None

    ####################################################################
    #
    def describe(self) -> str:
        """Render the change as a short human-readable line."""
        if self.old is None:
            return f"added {self.nickname!r} -> {self.new}"
        if self.new is None:
            return f"removed {self.nickname!r} (was {self.old})"
        return f"changed {self.nickname!r}: {self.old} -> {self.new}"


########################################################################
########################################################################
#
class AccountCache:
    """Nickname -> last-4 mapping persisted as JSON.

    File shape::

        {"format_version": 1, "accounts": {"Adv Plus Banking": "1234"}}

    Every mutation is recorded in `changes` so the run can report what
    it learned.  `save()` writes only when something changed.
    """

    ####################################################################
    #
    def __init__(self, path: Path, accounts: dict[str, str] | None = None):
        self.path = path
        self.accounts: dict[str, str] = dict(accounts or {})
        self.changes: list[CacheChange] = []

    ####################################################################
    #
    @classmethod
    def load(cls, path: Path) -> "AccountCache":
        """Load the cache from `path`; a missing file is an empty cache.

        An unreadable or malformed file is logged and treated as empty
        -- the cache is rebuildable, so it never blocks a run.
        """
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls(path)
        except (OSError, ValueError) as e:
            logger.warning("Ignoring unreadable account cache %s: %s", path, e)
            return cls(path)

        accounts = data.get("accounts") if isinstance(data, dict) else None
        if not isinstance(accounts, dict):
            logger.warning("Ignoring malformed account cache %s", path)
            return cls(path)
        return cls(
            path,
            {
                str(k): str(v)
                for k, v in accounts.items()
                if isinstance(v, str) and v
            },
        )

    ####################################################################
    #
    def get(self, nickname: str) -> str | None:
        """Return the cached last-4 for `nickname`, or None."""
        return self.accounts.get(nickname)

    ####################################################################
    #
    def record(self, nickname: str, last_four: str) -> CacheChange | None:
        """Record what an opened account showed.

        Returns:
            The change made, or None when the cache already agreed.
        """
        old = self.accounts.get(nickname)
        if old == last_four:
            return None
        self.accounts[nickname] = last_four
        change = CacheChange(nickname, old, last_four)
        self.changes.append(change)
        return change

    ####################################################################
    #
    def prune(self, keep: Iterable[str]) -> list[CacheChange]:
        """Remove every nickname not in `keep`.

        Returns:
            The removals made.
        """
        keep_set = set(keep)
        removed = [
            CacheChange(nickname, last_four, None)
            for nickname, last_four in sorted(self.accounts.items())
            if nickname not in keep_set
        ]
        for change in removed:
            del self.accounts[change.nickname]
        self.changes.extend(removed)
        return removed

    ####################################################################
    #
    def save(self) -> bool:
        """Write the cache if it changed, atomically and mode 0600.

        Returns:
            True when the file was written.
        """
        if not self.changes:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = json.dumps(
            {
                "format_version": ACCOUNT_CACHE_FORMAT_VERSION,
                "accounts": dict(sorted(self.accounts.items())),
            },
            indent=2,
        )
        fd, tmp_name = tempfile.mkstemp(
            dir=self.path.parent, prefix=f".{self.path.name}."
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(body + "\n")
            os.chmod(tmp_name, 0o600)
            os.replace(tmp_name, self.path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
        return True


####################################################################
#
def ambiguous_nicknames(nicknames: Iterable[str]) -> set[str]:
    """Return the nicknames used by more than one overview tile.

    These cannot key the cache, so their accounts are always opened.
    """
    return {name for name, n in Counter(nicknames).items() if n > 1}


####################################################################
#
def matches_filters(
    nickname: str, last_four: str | None, filters: Iterable[str]
) -> bool:
    """Whether an account passes the --account filters.

    A filter matches a case-insensitive substring of the nickname, or a
    substring of the last-4 when it is known.  No filters match
    everything.
    """
    filters = [f.lower() for f in filters]
    if not filters:
        return True
    name = nickname.lower()
    return any(f in name or (last_four and f in last_four) for f in filters)


####################################################################
#
def should_open(
    nickname: str,
    cached_last_four: str | None,
    tracked_last_fours: set[str] | None,
    filters: Iterable[str],
    check_all: bool,
) -> bool:
    """Decide whether to open an overview account before knowing its digits.

    Args:
        nickname: The account's overview nickname.
        cached_last_four: The cache's digits for the nickname, or None
            when unknown (pass None for an ambiguous nickname).
        tracked_last_fours: Last-4s of the mibudge accounts this run
            imports into, or None when every account is wanted
            (--save-only).
        filters: --account filters.
        check_all: --check-all-accounts.

    Returns:
        True when the account must be opened.
    """
    if check_all or cached_last_four is None:
        return True
    if not matches_filters(nickname, cached_last_four, filters):
        return False
    return tracked_last_fours is None or cached_last_four in tracked_last_fours


####################################################################
#
def index_tracked_accounts(
    bank_accounts: Iterable[dict[str, Any]],
    banks: Iterable[dict[str, Any]],
    bank_name: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """Index the mibudge accounts held at BofA by last-4.

    An account is tracked when its bank's name contains `bank_name`
    (case-insensitive) and it has an account number.

    Args:
        bank_accounts: `/api/v1/bank-accounts/` rows.
        banks: `/api/v1/banks/` rows.
        bank_name: Substring identifying the BofA bank row.

    Returns:
        A `(tracked, ambiguous)` tuple: `tracked` maps last-4 to the
        single account with those digits; `ambiguous` maps last-4 to
        the accounts that share them, which cannot be matched.
    """
    needle = bank_name.lower()
    bank_ids = {
        b["id"] for b in banks if needle in (b.get("name") or "").lower()
    }
    by_last_four: dict[str, list[dict[str, Any]]] = {}
    for acct in bank_accounts:
        number = acct.get("account_number") or ""
        if acct.get("bank") in bank_ids and len(number) >= 4:
            by_last_four.setdefault(number[-4:], []).append(acct)

    tracked = {k: v[0] for k, v in by_last_four.items() if len(v) == 1}
    ambiguous = {k: v for k, v in by_last_four.items() if len(v) > 1}
    return tracked, ambiguous


####################################################################
#
def missing_tracked_accounts(
    tracked: dict[str, dict[str, Any]], found_last_fours: Iterable[str]
) -> list[dict[str, Any]]:
    """Return the tracked accounts this run did not find on BofA.

    Returns:
        The missing accounts, ordered by name.
    """
    found = set(found_last_fours)
    return sorted(
        (acct for l4, acct in tracked.items() if l4 not in found),
        key=lambda a: a.get("name") or "",
    )
