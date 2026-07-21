"""
Shared BofA scraping primitives for the importers.

Everything here exists because BofA rate-limits detail-dialog opens
aggressively: a burst of ~40-50 opens in quick succession wedges the
page (the dialog stops opening) and can terminate the login session
entirely.  The machinery in this module paces fetches, detects the
wedge, and recovers when possible:

* `normalize_description` / `merchant_signature` / `txn_identity` --
  stable keys derived from scraped activity rows.
* `DetailsPacer` -- run-wide dialog-open budget + burst-limit pacing
  (the wedge is per login session, not per account, so one pacer is
  shared across every account in a run).
* `session_is_logged_out` / `recover_session` / `BofASessionLost` --
  wedge recovery: cool down, reload, re-expand, re-scrape.
* `fetch_details_for_account` -- the details-fetch loop used by the
  live importer, including the merchant-copy optimization: BofA's
  details are stable per merchant, so within a run each merchant
  signature is fetched ONCE and synthesized (minus the
  per-transaction virtual_card_number) for the merchant's other rows
  at zero dialog cost.

Empirical pacing defaults (from 2026-07 field runs against real
accounts): 3s between fetches, a 120s pause every 15 fetches, wedge
recovery after 3 consecutive failures with a 300s cooldown, give up
after 2 recoveries.  The default per-run fetch budget of 30 keeps a
run at two batches -- comfortably under the observed wedge burst.
"""

# system imports
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

# 3rd party imports
#
# selenium ships with the optional importers-bofa dependency group.
# Only the exception type is needed here; a stand-in keeps this module
# importable (and its fetch loop unit-testable with fakes) without it.
try:
    from selenium.common.exceptions import WebDriverException
except ImportError:  # pragma: no cover - envs without importers-bofa

    class WebDriverException(Exception):  # type: ignore[no-redef]
        """Stand-in when the optional selenium dependency is absent."""


logger = logging.getLogger(__name__)

# Empirical pacing defaults -- see module docstring.
#
DETAILS_FETCH_DELAY = 3.0
DETAILS_BATCH_SIZE = 15
DETAILS_BATCH_PAUSE = 120.0
WEDGE_THRESHOLD = 3
WEDGE_COOLDOWN = 300.0
MAX_RECOVERIES = 2

# Default run-wide detail-fetch budget for import_bofa_live.  Counted
# in dialog OPENS (merchant-copies are free).  0 disables details
# fetching entirely; a negative limit means unlimited (used by
# --save-only --details-all offline capture).
#
DEFAULT_DETAILS_LIMIT = 30

# Keys never propagated into a merchant-copy details payload:
# virtual_card_number is per-transaction, and the provenance keys are
# re-stamped per copy.
#
_COPY_EXCLUDED_KEYS = {"virtual_card_number", "details_source", "copied_from"}


########################################################################
########################################################################
#
def normalize_description(text: str) -> str:
    """Collapse a scraped description to match stored raw_description values.

    BofA appends extra text after a <br> tag (rendered as \\n by the
    scraper) for some pending transactions, e.g. "Amount may change -
    waiting for final amount from merchant".  Everything from the
    first \\n onwards is UI noise, not part of the transaction
    description.  Internal whitespace is collapsed to match the
    CSV-imported convention.

    Args:
        text: Raw description text from the scraper.

    Returns:
        The normalized single-line description.
    """
    text = text.split("\n")[0]
    return " ".join(text.split())


########################################################################
########################################################################
#
def merchant_signature(desc: str) -> str:
    """Reduce an activity-row description to a stable merchant key.

    Two transactions at the same merchant differ mostly in embedded
    dates, store numbers, card digits, and amounts.  Uppercase the
    description, drop every digit and punctuation character, collapse
    whitespace -- what survives ('COSTCO WHSE PURCHASE SPRINGFIELD IL')
    is stable per merchant, so detail fetches can be skipped once one
    transaction for the merchant has been handled.  Occasional
    over-merging is possible (digits are stripped, though the city
    usually survives); consumers must tolerate it -- the importer
    marks merchant copies with provenance so a mis-copy is visible
    and correctable.

    Args:
        desc: The normalized activity-row description.

    Returns:
        The merchant signature string (may be empty).
    """
    s = re.sub(r"[^A-Z&' ]", " ", desc.upper())
    return " ".join(s.split())


########################################################################
########################################################################
#
def txn_identity(txn: Any) -> tuple[str, str, float]:
    """Build a stable identity key for a scraped transaction.

    txn_hash is regenerated on every page render so it cannot be used
    to remember which rows were already processed across a recovery
    reload (or a later run); (date, normalized description, amount) is
    stable.  The amount is rounded to cents so it round-trips cleanly
    through JSON.

    Args:
        txn: A bofa_scraper transaction object.

    Returns:
        The (date, normalized_description, rounded_amount) tuple.
    """
    return (txn.date, normalize_description(txn.desc), round(txn.amount, 2))


########################################################################
########################################################################
#
class BofASessionLost(Exception):
    """BofA terminated the login session (anti-automation or timeout).

    Once this happens every tab is logged out, so the whole run should
    stop fetching details cleanly and continue with whatever was
    gathered.
    """


########################################################################
########################################################################
#
def session_is_logged_out(driver: Any) -> bool:
    """Best-effort check whether the browser landed on a logged-out page.

    After BofA kills a session, page loads redirect to the marketing /
    sign-in page, which carries the Online ID login field (id='oid')
    or a sign-off marker in the URL.

    Args:
        driver: The selenium WebDriver.

    Returns:
        True when the current page looks logged-out.
    """
    from selenium.webdriver.common.by import By

    url = driver.current_url or ""
    if "signOff" in url or "sign-off" in url.lower():
        return True
    return bool(driver.find_elements(By.ID, "oid"))


########################################################################
########################################################################
#
def recover_session(session: Any, load_more: int, cooldown: float) -> None:
    """Try to un-wedge a scrape session after repeated dialog failures.

    BofA stops serving the details dialog after a burst of opens
    (anti-automation).  Cool down, reload the account page, clear any
    blocking overlay, re-expand the transaction history (a reload
    resets it to the initial rows), and re-scrape so transactions get
    fresh session-scoped txn hashes.

    Args:
        session: The wedged ScrapeSession.
        load_more: How many times to re-click 'View more transactions'
            after the reload.
        cooldown: Seconds to sleep before reloading.

    Raises:
        BofASessionLost: When the reload lands on a logged-out page --
            BofA revoked the session, so recovery is impossible.
    """
    from selenium.common.exceptions import NoSuchElementException

    logger.warning(
        "Details dialog wedged; cooling down %.0fs then reloading the page",
        cooldown,
    )
    time.sleep(cooldown)
    session.driver.refresh()
    time.sleep(5)
    if session_is_logged_out(session.driver):
        raise BofASessionLost(
            "BofA logged the session out during the wedge cooldown."
        )
    session.dismiss_dialog()
    for _ in range(load_more):
        try:
            session.load_more_transactions()
        except NoSuchElementException:
            break
    session.scrape_transactions()


########################################################################
########################################################################
#
@dataclass
class DetailsPacer:
    """Run-wide detail-fetch budget and burst-limit pacing.

    One pacer is shared across every account in a run because the
    wedge/burst limit belongs to the BofA login session, not to an
    individual account page.

    `limit` counts dialog OPEN attempts (successes and failures both
    poke the dialog).  0 disables fetching; negative means unlimited.
    """

    limit: int = DEFAULT_DETAILS_LIMIT
    delay: float = DETAILS_FETCH_DELAY
    batch_size: int = DETAILS_BATCH_SIZE
    batch_pause: float = DETAILS_BATCH_PAUSE
    used: int = 0
    since_pause: int = 0

    @property
    def exhausted(self) -> bool:
        """Return True when the dialog-open budget is spent."""
        return self.limit >= 0 and self.used >= self.limit

    def pause_if_needed(self) -> None:
        """Proactively pause between fetch batches to dodge the burst limit."""
        if self.batch_size and self.since_pause >= self.batch_size:
            logger.info(
                "Pausing %.0fs after %d detail fetches (burst-limit avoidance)",
                self.batch_pause,
                self.since_pause,
            )
            time.sleep(self.batch_pause)
            self.since_pause = 0

    def record_attempt(self) -> None:
        """Charge one dialog open against the budget."""
        self.used += 1
        self.since_pause += 1


########################################################################
########################################################################
#
@dataclass
class DetailsFetchStats:
    """Counters returned by fetch_details_for_account."""

    fetched: int = 0
    copied: int = 0
    failed: int = 0
    skipped_no_details: int = 0
    skipped_budget: int = 0
    recoveries: int = 0


########################################################################
########################################################################
#
@dataclass
class _WorkRow:
    """Internal worklist entry for fetch_details_for_account.

    `txn` is dropped (set to None) when a wedge recovery re-scrapes
    the page -- the old objects hold stale session-scoped txn hashes
    -- and re-resolved from the fresh scrape via `identity`.
    `attempted` marks a row whose dialog fetch already failed (and was
    counted), so an unresolvable retry is not double-counted.
    """

    transaction_id: str
    identity: tuple[str, str, float]
    txn: Any = None
    attempted: bool = False


####################################################################
#
def synthesize_merchant_copy(
    details: dict[str, Any], source_transaction: str
) -> dict[str, Any]:
    """Build a merchant-copy details payload from a fetched one.

    BofA's per-transaction details are stable per merchant except for
    the virtual card number, so a fetched dict can seed the same
    merchant's other transactions.  The copy carries provenance
    (`details_source` = 'merchant-copy' plus the source transaction)
    and never the per-transaction `virtual_card_number`.

    Args:
        details: The fetched details dict (as submitted for its own
            transaction, i.e. possibly already carrying provenance).
        source_transaction: UUID string of the transaction the details
            were actually fetched for.

    Returns:
        A new details dict safe to apply to a sibling transaction.
    """
    copy = {k: v for k, v in details.items() if k not in _COPY_EXCLUDED_KEYS}
    copy["details_source"] = "merchant-copy"
    copy["copied_from"] = source_transaction
    return copy


########################################################################
########################################################################
#
def fetch_details_for_account(
    session: Any,
    account: Any,
    needed: list[tuple[str, Any]],
    pacer: DetailsPacer,
    seen_by_signature: dict[str, tuple[dict[str, Any], str]],
    load_more: int,
    wedge_threshold: int = WEDGE_THRESHOLD,
    wedge_cooldown: float = WEDGE_COOLDOWN,
    max_recoveries: int = MAX_RECOVERIES,
    copy_repeats: bool = True,
) -> tuple[list[dict[str, Any]], DetailsFetchStats]:
    """Fetch (or merchant-copy) details for one account's needed rows.

    Walks `needed` in the given order (callers pass newest-first).
    Each merchant signature is fetched at most once per run: repeat
    rows get a synthesized merchant-copy at zero dialog cost, so the
    dialog-open budget is spent only on unseen merchants.  Rows left
    unfetched when the budget runs out stay details-NULL server-side
    and are re-reported by the next sync's details_needed.

    Wedge handling: after `wedge_threshold`
    consecutive failures the page is cooled down, reloaded, and
    re-scraped via `recover_session`; the remaining worklist is then
    re-resolved against the fresh scrape by `txn_identity` (the old
    transaction objects hold stale session-scoped txn hashes).

    Args:
        session: An OPEN bofa_scraper ScrapeSession for the account.
        account: The bofa_scraper Account (transactions populated).
        needed: (transaction_uuid, scraped_txn) pairs to enrich,
            newest-first.  Rows whose txn lacks `has_details` are
            counted and skipped.
        pacer: The run-wide DetailsPacer (shared across accounts).
        seen_by_signature: Run-wide map of merchant signature ->
            (fetched details, source transaction uuid).  Updated in
            place.
        load_more: How many 'View more transactions' clicks a
            recovery reload must replay.
        wedge_threshold: Consecutive failures that trigger recovery
            (0 = never recover).
        wedge_cooldown: Seconds to cool down before a recovery reload.
        max_recoveries: Give up on the account after this many
            recoveries (remaining rows are left for the next run).
        copy_repeats: When False, disable the merchant-copy shortcut
            and fetch every row's real dialog -- used by offline
            captures (--save-only --details-all) where fidelity beats
            dialog cost.

    Returns:
        A (results, stats) tuple where results are JSON-ready
        ``{"transaction": uuid, "details": dict}`` items for the
        transaction-details endpoint.

    Raises:
        BofASessionLost: When BofA revoked the login session during a
            recovery -- the caller should stop fetching for the whole
            run (results gathered so far are NOT lost; they are
            returned attached to the exception as `partial_results`).
    """
    results: list[dict[str, Any]] = []
    stats = DetailsFetchStats()
    failure_streak = 0
    recoveries = 0

    worklist = [
        _WorkRow(
            transaction_id=tid,
            identity=txn_identity(txn),
            txn=txn,
        )
        for tid, txn in needed
    ]

    pos = 0
    while pos < len(worklist):
        row = worklist[pos]

        if row.txn is None:
            # Recovery invalidated the original object and
            # re-resolution found no match; the row stays
            # details-NULL server-side and is retried next run.
            if not row.attempted:
                stats.failed += 1
            pos += 1
            continue

        if not getattr(row.txn, "has_details", False):
            stats.skipped_no_details += 1
            pos += 1
            continue

        signature = merchant_signature(normalize_description(row.txn.desc))
        if copy_repeats and signature and signature in seen_by_signature:
            src_details, src_tid = seen_by_signature[signature]
            results.append(
                {
                    "transaction": row.transaction_id,
                    "details": synthesize_merchant_copy(src_details, src_tid),
                }
            )
            stats.copied += 1
            pos += 1
            continue

        if pacer.exhausted:
            # Keep walking: later rows may still be free merchant
            # copies of already-fetched signatures.
            stats.skipped_budget += 1
            pos += 1
            continue

        pacer.pause_if_needed()

        try:
            details = session.get_transaction_details(row.txn)
        except WebDriverException as exc:
            logger.warning(
                "Detail fetch failed for %r: %s",
                normalize_description(row.txn.desc),
                exc,
            )
            details = None
        pacer.record_attempt()

        if details is None:
            stats.failed += 1
            row.attempted = True
            failure_streak += 1
            # A blocking overlay (session-timeout warning, marketing
            # modal) can block clicks; try to clear it.
            session.dismiss_dialog()
            if wedge_threshold and failure_streak >= wedge_threshold:
                if recoveries >= max_recoveries:
                    logger.warning(
                        "Still wedged after %d recoveries; leaving the "
                        "remaining rows for the next run",
                        recoveries,
                    )
                    break
                recoveries += 1
                stats.recoveries += 1
                try:
                    recover_session(session, load_more, wedge_cooldown)
                except BofASessionLost as exc:
                    exc.partial_results = results  # type: ignore[attr-defined]
                    raise
                failure_streak = 0
                pacer.since_pause = 0
                _reresolve_worklist(worklist, pos, account)
                # Retry the current row (it was re-resolved too).
                continue
            time.sleep(pacer.delay)
            pos += 1
            continue

        failure_streak = 0
        details = dict(details)
        details["details_source"] = "bofa"
        results.append({"transaction": row.transaction_id, "details": details})
        stats.fetched += 1
        if signature:
            seen_by_signature[signature] = (details, row.transaction_id)
        pos += 1
        time.sleep(pacer.delay)

    return results, stats


####################################################################
#
def _reresolve_worklist(
    worklist: list[_WorkRow], start: int, account: Any
) -> None:
    """Re-bind worklist rows to fresh transaction objects after recovery.

    A recovery reload re-scrapes the page, so every previously held
    transaction object carries a stale session-scoped txn hash.  Match
    the remaining rows (from `start` onwards) to the fresh scrape by
    `txn_identity`; rows with no surviving match keep txn=None and are
    counted as failed when reached.

    Args:
        worklist: The full worklist (mutated in place).
        start: Index of the first row still to process.
        account: The account whose get_transactions() now returns the
            fresh post-recovery scrape.
    """
    fresh: dict[tuple[str, str, float], list[Any]] = {}
    for txn in account.get_transactions():
        fresh.setdefault(txn_identity(txn), []).append(txn)

    for row in worklist[start:]:
        bucket = fresh.get(row.identity)
        row.txn = bucket.pop(0) if bucket else None
