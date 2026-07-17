"""
Harvest Bank of America's transaction-category vocabulary.

Logs into Bank of America with the bofa_scraper Selenium/Firefox
driver, walks the posted transactions on each selected account, opens
each transaction's View/Edit dialog via
``ScrapeSession.get_transaction_details()`` (bofa-scraper >= 1.1.0),
and collects every distinct ``transaction_category`` string BofA uses
(e.g. ``'Groceries : Groceries'``).

For each distinct category string the script dry-runs the same
resolution rules the server-side resolver
(``moneypools.service.categories``) applies, against the planned
global category seed list, and writes a review YAML file::

    provider: bofa
    harvested_at: '2026-07-13T...'
    accounts:
    - 'Adv Plus Banking - 1234'
    categories:
    - raw: 'Groceries : Groceries'
      alias_key: 'groceries:groceries'
      count: 12
      samples:
      - 'CORNER MARKET 05/26 MOBILE PURCHASE SPRINGFIELD IL'
      match: subname
      confidence: medium
      category: 'Food & Drink : Groceries'

Review workflow: inspect each entry and edit ``category:`` where the
proposal is wrong (its value is the target category's full name,
``'{group} : {name}'``); delete entries that should not be seeded.
The reviewed file is then loaded by the idempotent
``seed_category_aliases`` management command on the server, which
creates any missing global categories and the alias rows.

``match`` / ``confidence`` legend:

* ``exact`` / ``high`` -- BofA's group and name match a planned global
  category exactly (case-insensitive).
* ``subname`` / ``medium`` -- only the name matched, exactly one
  planned category has it, and the name is not itself a group name.
* ``create`` / ``new`` -- no match; the proposal is a brand new global
  category pair (for BofA's single-level ``'X : X'`` form the proposal
  is group == name).

Because each detail fetch opens and closes a browser dialog, the
script paces itself (``--delay``) and supports ``--max-details`` /
``--stop-after-no-new`` to bound the run.  No mibudge server
connection is needed -- the dry run happens locally.

BofA rate-limits detail-dialog opens aggressively (a burst of a few
dozen wedges the page and can terminate the login session), so a
single run rarely covers every transaction.  The script keeps a
persistent accumulator (``--state``, default
``bofa-harvest-state.json``): each run loads it, skips everything
already gathered (known merchants and already-processed transactions),
spends its fetch budget only on transactions never seen before, and
saves the merged state back.  Run it repeatedly with the same state
file -- gently, spaced out -- to build up the full vocabulary over
time.  A prior run's ``--save-details`` JSON can seed the accumulator
via ``--import-details`` so those transactions are never re-fetched.

Requires the importers-bofa optional dependency group::

    uv sync --group importers-bofa
    uv run --group importers-bofa python -m importers.harvest_bofa_categories

BofA credentials are read exactly like import_bofa_live: BOFA_ID and
BOFA_PASSCODE env vars, --bofa-id / --bofa-passcode flags, or a
1Password item URL via BOFA_ONEPASSWORD_URL / --bofa-onepassword-url.
2FA: the scraper prompts for the code via stdin; run with
--no-headless to watch the browser.
"""

# system imports
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# 3rd party imports
import click
import yaml
from rich.console import Console
from rich.table import Table

# Project imports
# The scraping primitives (signature/identity keys, wedge recovery)
# live in bofa_common, shared with import_bofa_live's details fetch.
from importers.bofa_common import (
    BofASessionLost,
    merchant_signature,
    normalize_description,
    recover_session,
    session_is_logged_out,
    txn_identity,
)
from importers.import_bofa_live import (
    _read_bofa_credentials_from_1password,
    _setup_logging,
)
from importers.import_transactions import load_importer_env
from importers.theme import get_theme, theme_option

logger = logging.getLogger(__name__)

# The planned global TransactionCategory seed list -- the 150 rows that
# migration moneypools/0038 seeds (the old TextChoices enum minus the
# "Uncategorized:Unassigned" sentinel).  Inlined here because this
# script runs standalone on the scraping host with no Django or mibudge
# API access; the migration keeps the authoritative copy.
#
PLANNED_GLOBAL_CATEGORIES: list[tuple[str, str]] = [
    ("Business", "Business Clothing"),
    ("Business", "Business Services"),
    ("Business", "Business Supplies"),
    ("Business", "Meals"),
    ("Business", "Travel"),
    ("Children", "Activities"),
    ("Children", "Allowance"),
    ("Children", "Baby Supplies"),
    ("Children", "Childcare"),
    ("Children", "Kids Clothing"),
    ("Children", "Kids Education"),
    ("Children", "Toys"),
    ("Culture", "Art"),
    ("Culture", "Books"),
    ("Culture", "Dance"),
    ("Culture", "Games"),
    ("Culture", "Movies"),
    ("Culture", "Music"),
    ("Culture", "News"),
    ("Culture", "Random Fun"),
    ("Culture", "TV"),
    ("Education", "Books & Supplies"),
    ("Education", "Room & Board"),
    ("Education", "Student Loans"),
    ("Education", "Tuition & Fees"),
    ("Fees", "ATM Fees"),
    ("Fees", "Investment Fees"),
    ("Fees", "Other Fees"),
    ("Financial", "Accounting"),
    ("Financial", "Credit Card Payment"),
    ("Financial", "Financial Advice"),
    ("Financial", "Life Insurance"),
    ("Financial", "Loan"),
    ("Financial", "Loan Payment"),
    ("Financial", "Money Transfers"),
    ("Financial", "Other Financial"),
    ("Financial", "Tax Preparation"),
    ("Financial", "Taxes, Federal"),
    ("Financial", "Taxes, Other"),
    ("Financial", "Taxes, State"),
    ("Food & Drink", "Alcohol & Bars"),
    ("Food & Drink", "Coffee & Tea"),
    ("Food & Drink", "Dessert"),
    ("Food & Drink", "Fast Food"),
    ("Food & Drink", "Groceries"),
    ("Food & Drink", "Other Food & Drink"),
    ("Food & Drink", "Restaurants"),
    ("Food & Drink", "Snacks"),
    ("Food & Drink", "Tobacco & Like"),
    ("Gifts & Donations", "Charities"),
    ("Gifts & Donations", "Gifts"),
    ("Health & Medical", "Care Facilities"),
    ("Health & Medical", "Dentist"),
    ("Health & Medical", "Doctor"),
    ("Health & Medical", "Equipment"),
    ("Health & Medical", "Eyes"),
    ("Health & Medical", "Health Insurance"),
    ("Health & Medical", "Other Health & Medical"),
    ("Health & Medical", "Pharmacies"),
    ("Health & Medical", "Prescriptions"),
    ("Home", "Furnishings"),
    ("Home", "Home Insurance"),
    ("Home", "Home Purchase"),
    ("Home", "Home Services"),
    ("Home", "Home Supplies"),
    ("Home", "Lawn & Garden"),
    ("Home", "Mortgage"),
    ("Home", "Moving"),
    ("Home", "Other Home"),
    ("Home", "Property Tax"),
    ("Home", "Rent"),
    ("Home", "Renter's Insurance"),
    ("Income", "Bonus"),
    ("Income", "Commission"),
    ("Income", "Interest"),
    ("Income", "Other Income"),
    ("Income", "Paycheck"),
    ("Income", "Reimbursement"),
    ("Income", "Rental Income"),
    ("Investment", "Education Investment"),
    ("Investment", "Other Investments"),
    ("Investment", "Retirement"),
    ("Investment", "Stocks & Mutual Funds"),
    ("Legal", "Legal Fees"),
    ("Legal", "Legal Services"),
    ("Legal", "Other Legal Costs"),
    ("Office", "Equipment"),
    ("Office", "Office Supplies"),
    ("Office", "Other Office"),
    ("Office", "Postage & Shipping"),
    ("Personal", "Accessories"),
    ("Personal", "Beauty"),
    ("Personal", "Body Enhancement"),
    ("Personal", "Clothing"),
    ("Personal", "Counseling"),
    ("Personal", "Hair"),
    ("Personal", "Hobbies"),
    ("Personal", "Jewelry"),
    ("Personal", "Laundry"),
    ("Personal", "Other Personal"),
    ("Personal", "Religion"),
    ("Personal", "Shoes"),
    ("Pets", "Pet Food"),
    ("Pets", "Pet Grooming"),
    ("Pets", "Pet Medicine"),
    ("Pets", "Pet Supplies"),
    ("Pets", "Veterinarian"),
    ("Sports & Fitness", "Camping"),
    ("Sports & Fitness", "Fitness Gear"),
    ("Sports & Fitness", "Golf"),
    ("Sports & Fitness", "Memberships"),
    ("Sports & Fitness", "Other Sports & Fitness"),
    ("Sports & Fitness", "Sporting Events"),
    ("Sports & Fitness", "Sporting Goods"),
    ("Technology", "Domains & Hosting"),
    ("Technology", "Hardware"),
    ("Technology", "Online Services"),
    ("Technology", "Software"),
    ("Transportation", "Auto Insurance"),
    ("Transportation", "Auto Payment"),
    ("Transportation", "Auto Services"),
    ("Transportation", "Auto Supplies"),
    ("Transportation", "Bicycle"),
    ("Transportation", "Boats & Marine"),
    ("Transportation", "Gas"),
    ("Transportation", "Other Transportation"),
    ("Transportation", "Parking & Tolls"),
    ("Transportation", "Parking Tickets"),
    ("Transportation", "Public Transit"),
    ("Transportation", "Shipping"),
    ("Transportation", "Taxies"),
    ("Travel", "Car Rental"),
    ("Travel", "Flights"),
    ("Travel", "Hotels"),
    ("Travel", "Tours & Cruises"),
    ("Travel", "Train"),
    ("Travel", "Travel Buses"),
    ("Travel", "Travel Dining"),
    ("Travel", "Travel Entertainment"),
    ("Uncategorized", "Cash"),
    ("Uncategorized", "Other Shopping"),
    ("Uncategorized", "Unknown"),
    ("Utilities", "Cable"),
    ("Utilities", "Electricity"),
    ("Utilities", "Gas & Fuel"),
    ("Utilities", "Internet"),
    ("Utilities", "Other Utilities"),
    ("Utilities", "Phone"),
    ("Utilities", "Trash"),
    ("Utilities", "Water & Sewer"),
]

MAX_SAMPLES_PER_CATEGORY = 3


########################################################################
########################################################################
#
def normalize_category(raw: str) -> tuple[str, str]:
    """Split a raw provider category string into (group, name).

    Mirrors the server-side normalization in
    moneypools.service.categories: split on the FIRST colon, strip
    each side, collapse internal whitespace.  A string with no colon
    is a single-level category and maps to group == name.

    Args:
        raw: The provider's category string
            (e.g. 'Groceries : Groceries').

    Returns:
        A (group, name) tuple.
    """
    group, sep, name = raw.partition(":")
    group = " ".join(group.split())
    if not sep:
        return group, group
    name = " ".join(name.split())
    return group, name or group


####################################################################
#
def alias_key(group: str, name: str) -> str:
    """Build the normalized alias-table key for a (group, name) pair.

    Args:
        group: Normalized group string.
        name: Normalized name string.

    Returns:
        The 'group:name' key, casefolded.
    """
    return f"{group}:{name}".casefold()


########################################################################
########################################################################
#
def dry_run_resolve(group: str, name: str) -> tuple[str, str, str | None]:
    """Dry-run the server resolver rules against the planned seed list.

    Applies the non-alias resolution steps of
    moneypools.service.categories.resolve_provider_category:

    1. Exact full-name match (case-insensitive on group AND name).
    2. Unique sub-name match, guarded: skipped when the name is also
       an existing group name (else BofA 'Travel : Travel' would
       mis-map to 'Business : Travel').
    3. Otherwise the pair would be auto-created as a global category.

    Args:
        group: Normalized group from the provider string.
        name: Normalized name from the provider string.

    Returns:
        A (match, confidence, category_full_name) tuple where match is
        'exact', 'subname', or 'create' and category_full_name is the
        proposed target ('{group} : {name}').
    """
    gkey, nkey = group.casefold(), name.casefold()
    groups = {g.casefold() for g, _ in PLANNED_GLOBAL_CATEGORIES}

    for g, n in PLANNED_GLOBAL_CATEGORIES:
        if g.casefold() == gkey and n.casefold() == nkey:
            return "exact", "high", f"{g} : {n}"

    sub_matches = [
        (g, n) for g, n in PLANNED_GLOBAL_CATEGORIES if n.casefold() == nkey
    ]
    if len(sub_matches) == 1 and nkey not in groups:
        g, n = sub_matches[0]
        return "subname", "medium", f"{g} : {n}"

    return "create", "new", f"{group} : {name}"


########################################################################
########################################################################
#
@dataclass
class HarvestedCategory:
    """Aggregate for one distinct BofA category string."""

    raw: str
    count: int = 0
    samples: list[str] = field(default_factory=list)

    ####################################################################
    #
    def add_sample(self, description: str) -> None:
        """Record an occurrence, keeping a few distinct sample strings."""
        self.count += 1
        if (
            len(self.samples) < MAX_SAMPLES_PER_CATEGORY
            and description not in self.samples
        ):
            self.samples.append(description)

    ####################################################################
    #
    def to_dict(self) -> dict[str, Any]:
        """Serialize for the JSON state file."""
        return {
            "raw": self.raw,
            "count": self.count,
            "samples": list(self.samples),
        }

    ####################################################################
    #
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HarvestedCategory":
        """Reconstruct from a state-file dict."""
        return cls(
            raw=data["raw"],
            count=int(data.get("count", 0)),
            samples=list(data.get("samples", [])),
        )


########################################################################
########################################################################
#
STATE_VERSION = 1


@dataclass
class HarvestState:
    """Persistent accumulator so harvests build up incrementally.

    Because a category is stable per merchant and BofA rate-limits
    detail-dialog opens hard, a single run rarely covers every
    transaction.  Persisting this state between runs lets each run skip
    everything already gathered -- known merchants and
    already-processed transactions -- and spend its limited fetch
    budget only on transactions it has never seen, gradually building
    up the full category vocabulary across many gentle runs.

    Fields:
        seen_merchants: merchant signature -> resolved alias key (or
            None when that merchant's details carried no category).
            A signature present here is never fetched again.
        vocab: alias key -> HarvestedCategory aggregate.
        processed: identities of transactions already handled (fetched
            or credited); never re-fetched or re-counted.
        accounts_seen: BofA account names harvested at least once.
    """

    seen_merchants: dict[str, str | None] = field(default_factory=dict)
    vocab: dict[str, HarvestedCategory] = field(default_factory=dict)
    processed: set[tuple[str, str, float]] = field(default_factory=set)
    accounts_seen: list[str] = field(default_factory=list)


####################################################################
#
def load_state(path: Path) -> HarvestState:
    """Load the accumulator state file, or return an empty one.

    Args:
        path: Path to the JSON state file.

    Returns:
        The loaded HarvestState (empty if the file does not exist).

    Raises:
        click.ClickException: If the file exists but has an
            unsupported version.
    """
    if not path.exists():
        return HarvestState()
    data = json.loads(path.read_text(encoding="utf-8"))
    version = data.get("version")
    if version != STATE_VERSION:
        raise click.ClickException(
            f"{path}: unsupported state version {version!r} "
            f"(expected {STATE_VERSION}).  Delete it to start fresh, or "
            "point --state at a new file."
        )
    return HarvestState(
        seen_merchants=dict(data.get("seen_merchants", {})),
        vocab={
            key: HarvestedCategory.from_dict(value)
            for key, value in data.get("vocab", {}).items()
        },
        processed={tuple(item) for item in data.get("processed", [])},
        accounts_seen=list(data.get("accounts_seen", [])),
    )


####################################################################
#
def seed_state_from_details(
    state: HarvestState, records: list[dict[str, Any]]
) -> int:
    """Merge saved --save-details records into the accumulator state.

    Bootstraps the state from a previous run's details JSON so those
    transactions and merchants are never re-fetched.  Idempotent:
    records whose transaction identity is already processed are
    skipped.

    Args:
        state: The HarvestState to update in place.
        records: Details records, each with keys account/date/desc/
            amount/details (as written by --save-details).

    Returns:
        The number of records newly merged.
    """
    merged = 0
    for record in records:
        date = record.get("date")
        desc = record.get("desc") or ""
        amount = record.get("amount")
        if date is None or amount is None:
            continue
        identity = (date, desc, round(float(amount), 2))
        if identity in state.processed:
            continue
        state.processed.add(identity)
        merged += 1

        details = record.get("details") or {}
        raw_category = (details.get("transaction_category") or "").strip()
        signature = merchant_signature(desc)
        if raw_category:
            key = alias_key(*normalize_category(raw_category))
            harvested = state.vocab.get(key)
            if harvested is None:
                harvested = state.vocab[key] = HarvestedCategory(
                    raw=raw_category
                )
            harvested.add_sample(desc)
            if signature:
                state.seen_merchants[signature] = key
        elif signature:
            state.seen_merchants.setdefault(signature, None)
    return merged


####################################################################
#
def save_state(path: Path, state: HarvestState, updated_at: datetime) -> None:
    """Atomically write the accumulator state file.

    Args:
        path: Destination path.
        state: The state to persist.
        updated_at: Wall-clock UTC datetime of this save.
    """
    data = {
        "version": STATE_VERSION,
        "provider": "bofa",
        "updated_at": updated_at.isoformat(),
        "accounts_seen": sorted(set(state.accounts_seen)),
        "seen_merchants": state.seen_merchants,
        "vocab": {key: hc.to_dict() for key, hc in state.vocab.items()},
        "processed": [list(item) for item in sorted(state.processed)],
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


########################################################################
########################################################################
#
def build_review_entries(
    vocab: dict[str, HarvestedCategory],
) -> list[dict[str, Any]]:
    """Convert harvested aggregates into review-YAML entries.

    Args:
        vocab: Map of normalized alias key -> HarvestedCategory.

    Returns:
        List of YAML-ready dicts sorted by raw category string.
    """
    entries: list[dict[str, Any]] = []
    for harvested in sorted(vocab.values(), key=lambda h: h.raw.casefold()):
        group, name = normalize_category(harvested.raw)
        match, confidence, proposed = dry_run_resolve(group, name)
        entries.append(
            {
                "raw": harvested.raw,
                "alias_key": alias_key(group, name),
                "count": harvested.count,
                "samples": harvested.samples,
                "match": match,
                "confidence": confidence,
                "category": proposed,
            }
        )
    return entries


########################################################################
########################################################################
#
def write_review_yaml(
    output: Path,
    entries: list[dict[str, Any]],
    account_names: list[str],
    harvested_at: datetime,
) -> None:
    """Write the review YAML file consumed by seed_category_aliases.

    Args:
        output: Destination file path.
        entries: Entries from build_review_entries().
        account_names: BofA account names that were harvested.
        harvested_at: Wall-clock UTC datetime of the harvest.
    """
    header = (
        "# BofA transaction-category harvest -- review before seeding.\n"
        "#\n"
        "# For each entry, 'category' is the proposed mibudge category\n"
        "# (full name, '{group} : {name}').  Edit it where the proposal\n"
        "# is wrong; delete entries that should not be seeded.  Load the\n"
        "# reviewed file with:\n"
        "#\n"
        "#   uv run python app/manage.py seed_category_aliases <file>\n"
        "#\n"
        "# match/confidence: exact/high = full-name match on the global\n"
        "# list; subname/medium = unique sub-name match; create/new = no\n"
        "# match, a new global category pair will be created.\n"
    )
    doc = {
        "provider": "bofa",
        "harvested_at": harvested_at.isoformat(),
        "accounts": account_names,
        "categories": entries,
    }
    with output.open("w", encoding="utf-8") as fh:
        fh.write(header)
        yaml.safe_dump(doc, fh, sort_keys=False, allow_unicode=True, width=78)


########################################################################
########################################################################
#
def harvest_account(
    session: Any,
    account: Any,
    vocab: dict[str, HarvestedCategory],
    details_log: list[dict[str, Any]] | None,
    load_more: int,
    delay: float,
    max_details: int,
    stop_after_no_new: int,
    wedge_threshold: int,
    wedge_cooldown: float,
    max_recoveries: int,
    batch_size: int,
    batch_pause: float,
    seen_merchants: dict[str, str | None] | None,
    processed: set[tuple[str, str, float]],
    console: Console,
    interactive: bool,
) -> tuple[int, int, int]:
    """Fetch details for one account's posted transactions.

    BofA rate-limits dialog opens (empirically: a burst of ~40-50 in
    quick succession wedges the page -- the details dialog stops
    opening entirely).  Two defenses: a proactive pause every
    batch_size fetches, and wedge recovery -- after wedge_threshold
    consecutive failures the page is cooled down, reloaded, and
    re-scraped, then the walk resumes with the already-processed rows
    skipped.

    Args:
        session: An open bofa_scraper ScrapeSession for the account.
        account: The bofa_scraper Account (transactions populated by
            the caller).
        vocab: Shared map of alias key -> HarvestedCategory, updated
            in place.
        details_log: When not None, every fetched details dict is
            appended here (for --save-details).
        load_more: How many times the caller expanded the history;
            recovery reloads must re-expand the same amount.
        delay: Seconds to sleep between detail fetches.
        max_details: Stop after this many fetches (0 = unlimited).
        stop_after_no_new: Stop after this many consecutive fetches
            that yielded no new category (0 = disabled).
        wedge_threshold: Consecutive failures that trigger recovery
            (0 = never recover, fail through).
        wedge_cooldown: Seconds to cool down before a recovery reload.
        max_recoveries: Give up on the account after this many
            recoveries.
        batch_size: Proactively pause after this many fetches
            (0 = disabled).
        batch_pause: Seconds to pause between batches.
        seen_merchants: When not None, a shared map of merchant
            signature -> alias key (or None when the merchant's details
            had no category).  Transactions whose merchant was already
            harvested are skipped without opening the dialog; their
            occurrence is still credited to the remembered category.
        processed: Shared, persisted set of transaction identities
            already handled (fetched or credited).  Preloaded from the
            state file so a transaction gathered in an earlier run is
            neither re-fetched nor re-counted; updated in place as new
            transactions are handled.
        console: Rich console for interactive output.
        interactive: Whether to render progress via Rich.

    Returns:
        A (fetched, failed, skipped) tuple of detail-fetch counts.
    """
    from selenium.common.exceptions import WebDriverException

    acct_name = account.get_name()
    total_with_details = sum(
        1 for t in account.get_transactions() if t.has_details
    )
    if interactive:
        console.print(
            f"[dim]{total_with_details} posted transaction(s) with "
            f"details; fetching...[/dim]"
        )
    else:
        logger.info(
            "%s: fetching details for %d posted transaction(s)",
            acct_name,
            total_with_details,
        )

    fetched = 0
    failed = 0
    skipped = 0
    no_new_streak = 0
    failure_streak = 0
    recoveries = 0
    since_batch_pause = 0
    done = False

    while not done:
        # (Re)build the worklist from the current scrape.  'processed'
        # (preloaded from the state file, updated in place) excludes
        # transactions handled in an earlier run or before a recovery
        # reload, so we never re-fetch or re-count them.
        txns = [
            t
            for t in account.get_transactions()
            if t.has_details and txn_identity(t) not in processed
        ]
        if not txns:
            break
        done = True  # unless a wedge recovery asks for another pass

        for txn in txns:
            if max_details and fetched >= max_details:
                logger.info(
                    "%s: --max-details=%d reached", acct_name, max_details
                )
                return fetched, failed, skipped
            if stop_after_no_new and no_new_streak >= stop_after_no_new:
                logger.info(
                    "%s: no new category in %d consecutive fetches; stopping",
                    acct_name,
                    no_new_streak,
                )
                return fetched, failed, skipped

            desc = normalize_description(txn.desc)
            signature = merchant_signature(desc)

            # Same merchant, same category -- skip the dialog
            # round-trip and credit the occurrence to the remembered
            # category.
            if seen_merchants is not None and signature in seen_merchants:
                skipped += 1
                processed.add(txn_identity(txn))
                known_key = seen_merchants[signature]
                if known_key is not None and known_key in vocab:
                    vocab[known_key].add_sample(desc)
                continue

            # Proactive pause so we (hopefully) never trip BofA's
            # burst limit in the first place.
            if batch_size and since_batch_pause >= batch_size:
                logger.info(
                    "%s: pausing %.0fs after %d fetches (burst-limit "
                    "avoidance)",
                    acct_name,
                    batch_pause,
                    since_batch_pause,
                )
                time.sleep(batch_pause)
                since_batch_pause = 0

            try:
                details = session.get_transaction_details(txn)
            except WebDriverException as exc:
                logger.warning(
                    "%s: detail fetch failed for %r: %s", acct_name, desc, exc
                )
                details = None

            if details is None:
                failed += 1
                failure_streak += 1
                since_batch_pause += 1
                # A blocking overlay (session-timeout warning,
                # marketing modal) can block clicks; try to clear it.
                session.dismiss_dialog()
                if wedge_threshold and failure_streak >= wedge_threshold:
                    if recoveries >= max_recoveries:
                        logger.warning(
                            "%s: still wedged after %d recoveries; giving "
                            "up on this account",
                            acct_name,
                            recoveries,
                        )
                        return fetched, failed, skipped
                    recoveries += 1
                    recover_session(session, load_more, wedge_cooldown)
                    failure_streak = 0
                    since_batch_pause = 0
                    done = False  # rebuild the worklist and resume
                    break
                time.sleep(delay)
                continue

            fetched += 1
            since_batch_pause += 1
            failure_streak = 0
            processed.add(txn_identity(txn))

            if details_log is not None:
                details_log.append(
                    {
                        "account": acct_name,
                        "date": txn.date,
                        "desc": desc,
                        "amount": txn.amount,
                        "details": details,
                    }
                )

            raw_category = (details.get("transaction_category") or "").strip()
            if raw_category:
                key = alias_key(*normalize_category(raw_category))
                harvested = vocab.get(key)
                if harvested is None:
                    vocab[key] = harvested = HarvestedCategory(raw=raw_category)
                    no_new_streak = 0
                    if interactive:
                        console.print(
                            f"  [success]new[/success] {raw_category!r}"
                        )
                    else:
                        logger.info("new category: %r", raw_category)
                else:
                    no_new_streak += 1
                harvested.add_sample(desc)
                if seen_merchants is not None and signature:
                    seen_merchants[signature] = key
            else:
                no_new_streak += 1
                if seen_merchants is not None and signature:
                    seen_merchants[signature] = None

            time.sleep(delay)

    return fetched, failed, skipped


########################################################################
########################################################################
#
@click.command(
    help=(
        "Harvest BofA's transaction-category vocabulary.  Logs in via the "
        "bofa_scraper Selenium/Firefox driver, opens each posted "
        "transaction's View/Edit dialog, and collects every distinct "
        "'Transaction category' string into a review YAML file for the "
        "seed_category_aliases management command.  Needs no mibudge "
        "server connection.\n\n"
        "BofA credentials are read from BOFA_ID and BOFA_PASSCODE env "
        "vars (or --bofa-id / --bofa-passcode), or from 1Password via "
        "BOFA_ONEPASSWORD_URL.  If BofA requires 2FA the scraper prompts "
        "for the code via stdin; run with --no-headless to watch the "
        "browser."
    ),
)
@click.option(
    "--bofa-id",
    envvar="BOFA_ID",
    default=None,
    help="BofA online ID (env var: BOFA_ID).",
)
@click.option(
    "--bofa-passcode",
    envvar="BOFA_PASSCODE",
    default=None,
    help="BofA passcode (env var: BOFA_PASSCODE; prefer env over CLI flag).",
)
@click.option(
    "--bofa-onepassword-url",
    envvar="BOFA_ONEPASSWORD_URL",
    default=None,
    help=(
        "1Password item URL to source BofA credentials from "
        "(e.g. 'op://Personal/BofA').  Env var: BOFA_ONEPASSWORD_URL."
    ),
)
@click.option(
    "--headless/--no-headless",
    default=True,
    show_default=True,
    help="Run Firefox headlessly (default) or visibly for debugging/2FA.",
)
@click.option(
    "--timeout",
    default=5,
    type=float,
    show_default=True,
    help="Selenium page-load timeout in seconds.",
)
@click.option(
    "--account",
    "-a",
    "account_filters",
    multiple=True,
    help=(
        "Filter by BofA account name substring (e.g. 'Checking' or "
        "'1234').  Repeatable; when omitted all accessible accounts "
        "are harvested."
    ),
)
@click.option(
    "--load-more",
    default=2,
    show_default=True,
    type=int,
    help=(
        "How many times to click BofA's 'View more transactions' before "
        "harvesting, to include older history."
    ),
)
@click.option(
    "--delay",
    default=3.0,
    show_default=True,
    type=float,
    help=(
        "Seconds to sleep between detail fetches.  Each fetch opens and "
        "closes a browser dialog; keep this gentle to avoid BofA "
        "rate-limiting."
    ),
)
@click.option(
    "--max-details",
    default=0,
    show_default=True,
    type=int,
    help="Max detail fetches per account (0 = unlimited).",
)
@click.option(
    "--stop-after-no-new",
    default=0,
    show_default=True,
    type=int,
    help=(
        "Stop an account after this many consecutive detail fetches "
        "that yielded no new category (0 = disabled).  Useful once the "
        "vocabulary has plateaued -- category counts will be "
        "undercounted."
    ),
)
@click.option(
    "--wedge-threshold",
    default=3,
    show_default=True,
    type=int,
    help=(
        "Consecutive detail-fetch failures that mean the page is "
        "wedged (BofA burst limit); triggers a cooldown + page reload "
        "(0 = never recover)."
    ),
)
@click.option(
    "--wedge-cooldown",
    default=300.0,
    show_default=True,
    type=float,
    help="Seconds to cool down before a wedge-recovery page reload.",
)
@click.option(
    "--max-recoveries",
    default=2,
    show_default=True,
    type=int,
    help="Give up on an account after this many wedge recoveries.",
)
@click.option(
    "--batch-size",
    default=15,
    show_default=True,
    type=int,
    help=(
        "Proactively pause after this many detail fetches to stay "
        "under BofA's burst limit (0 = disabled)."
    ),
)
@click.option(
    "--batch-pause",
    default=120.0,
    show_default=True,
    type=float,
    help="Seconds to pause between fetch batches.",
)
@click.option(
    "--skip-known-merchants/--no-skip-known-merchants",
    default=True,
    show_default=True,
    help=(
        "Skip detail fetches for transactions whose merchant (derived "
        "from the description with digits/punctuation stripped) was "
        "already harvested -- same merchant, same category.  Skipped "
        "occurrences still count toward the remembered category."
    ),
)
@click.option(
    "--state",
    default="bofa-harvest-state.json",
    show_default=True,
    type=click.Path(dir_okay=False, writable=True, path_type=Path),
    help=(
        "Persistent accumulator file.  Loaded at startup and saved at "
        "the end (and on interrupt), so each run skips everything "
        "already gathered -- known merchants and already-processed "
        "transactions -- and spends its fetch budget only on "
        "transactions never seen before.  Run repeatedly with the same "
        "file to build up the full category list over time."
    ),
)
@click.option(
    "--reset-state",
    is_flag=True,
    help="Ignore any existing --state file and start a fresh accumulator.",
)
@click.option(
    "--import-details",
    default=None,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help=(
        "Bootstrap the accumulator from a previous run's --save-details "
        "JSON so those transactions and merchants are not re-fetched.  "
        "Idempotent; merged into --state before harvesting."
    ),
)
@click.option(
    "--output",
    "-o",
    default=None,
    type=click.Path(dir_okay=False, writable=True, path_type=Path),
    help=(
        "Review YAML destination.  [default: bofa-categories-<timestamp>.yaml]"
    ),
)
@click.option(
    "--save-details",
    default=None,
    type=click.Path(dir_okay=False, writable=True, path_type=Path),
    help=(
        "Also save every fetched details dict (with account/date/"
        "desc/amount context) to this JSON file -- useful test data "
        "for the transaction-details enrichment work."
    ),
)
@click.option("--verbose", "-v", is_flag=True, help="Enable DEBUG logging.")
@click.option(
    "--plain",
    is_flag=True,
    help="Disable rich output (auto-disabled when not a TTY).",
)
@theme_option
def cli_cmd(
    bofa_id: str | None,
    bofa_passcode: str | None,
    bofa_onepassword_url: str | None,
    headless: bool,
    timeout: float,
    account_filters: tuple[str, ...],
    load_more: int,
    delay: float,
    max_details: int,
    stop_after_no_new: int,
    wedge_threshold: int,
    wedge_cooldown: float,
    max_recoveries: int,
    batch_size: int,
    batch_pause: float,
    skip_known_merchants: bool,
    state: Path,
    reset_state: bool,
    import_details: Path | None,
    output: Path | None,
    save_details: Path | None,
    verbose: bool,
    plain: bool,
    theme_name: str,
) -> None:
    """CLI entry point for the BofA category harvester."""
    if bofa_onepassword_url is not None:
        bofa_id, bofa_passcode = _read_bofa_credentials_from_1password(
            bofa_onepassword_url
        )
    else:
        if bofa_id is None:
            bofa_id = click.prompt("BofA Online ID")
        if bofa_passcode is None:
            bofa_passcode = click.prompt("BofA Passcode", hide_input=True)

    console = Console(theme=get_theme(theme_name).rich, stderr=True)
    interactive = console.is_terminal and not plain
    _setup_logging(verbose, interactive, console=console)

    harvested_at = datetime.now(UTC)
    if output is None:
        ts = harvested_at.strftime("%Y-%m-%d-%H%M%S")
        output = Path(f"bofa-categories-{ts}.yaml")

    # --- Load the persistent accumulator ---
    harvest_state = HarvestState() if reset_state else load_state(state)
    if not reset_state and (harvest_state.vocab or harvest_state.processed):
        logger.info(
            "Loaded state from %s: %d categories, %d known merchants, "
            "%d transactions already processed.",
            state,
            len(harvest_state.vocab),
            len(harvest_state.seen_merchants),
            len(harvest_state.processed),
        )

    if import_details is not None:
        records = json.loads(import_details.read_text(encoding="utf-8"))
        merged = seed_state_from_details(harvest_state, records)
        logger.info(
            "Imported %d new record(s) from %s into the accumulator.",
            merged,
            import_details,
        )

    # --- Lazy-import scraper so missing deps fail with a friendly message ---
    try:
        from bofa_scraper import BofAScraper
        from selenium.common.exceptions import (
            NoSuchElementException,
            WebDriverException,
        )
    except ImportError as e:
        raise click.ClickException(
            f"bofa_scraper / selenium are not installed ({e}). "
            "Install the importers-bofa dependency group:\n"
            "  uv sync --group importers-bofa"
        ) from e

    # --- Launch browser ---
    if interactive:
        console.print("[bold]Initializing browser...[/bold]")
    else:
        logger.info("Initializing browser (headless=%s)...", headless)

    try:
        scraper = BofAScraper(
            bofa_id,
            bofa_passcode,
            timeout_duration=timeout,
            headless=headless,
            verbose=verbose,
        )
    except WebDriverException as e:
        raise click.ClickException(f"Failed to launch browser: {e}") from e

    # Accumulators live on harvest_state so they persist across runs.
    vocab = harvest_state.vocab
    processed = harvest_state.processed
    details_log: list[dict[str, Any]] | None = (
        [] if save_details is not None else None
    )
    # Merchant signature -> alias key, shared across accounts (and runs)
    # so a merchant seen once is skipped everywhere after.
    seen_merchants: dict[str, str | None] | None = (
        harvest_state.seen_merchants if skip_known_merchants else None
    )
    harvested_names: list[str] = []
    any_error = False
    total_fetched = 0
    total_failed = 0
    total_skipped = 0
    try:
        # --- Log in to BofA ---
        if interactive:
            console.print("[bold]Logging in to Bank of America...[/bold]")
        else:
            logger.info("Logging in to Bank of America...")

        scraper.login()

        if not scraper.logged_in:
            raise click.ClickException(
                "BofA login failed. Check credentials or run with "
                "--no-headless to inspect the browser state."
            )
        if interactive:
            console.print("[success]Logged in to BofA.[/success]")
        else:
            logger.info("BofA login successful.")

        # --- Collect and filter accounts ---
        accounts = scraper.get_accounts()
        if not accounts:
            raise click.ClickException(
                "No BofA accounts found after login. The page layout may "
                "have changed; run with --no-headless to inspect."
            )

        all_names = [a.get_name() for a in accounts]
        if account_filters:
            filters_lower = [f.lower() for f in account_filters]
            selected_names = [
                n
                for n in all_names
                if any(f in n.lower() for f in filters_lower)
            ]
            if not selected_names:
                raise click.ClickException(
                    f"No BofA accounts matched filter(s) "
                    f"{list(account_filters)}. "
                    f"Available: {all_names}."
                )
        else:
            selected_names = list(all_names)

        if interactive:
            console.print(
                f"[dim]Found {len(accounts)} BofA account(s); "
                f"harvesting {len(selected_names)}.[/dim]"
            )

        # --- Harvest each account ---
        # Details must be fetched while the account's scrape session
        # (browser tab) is still open -- txn_hash values are
        # session-scoped.
        for acct_name in selected_names:
            if interactive:
                console.rule(f"[bold]{acct_name}[/bold]")
            else:
                logger.info("--- Harvesting account: %s ---", acct_name)

            try:
                # Re-locate the account tile fresh for each account --
                # WebElement references from the initial get_accounts()
                # go stale while earlier accounts are harvested (BofA
                # re-renders the overview page over time).
                account = next(
                    (
                        a
                        for a in scraper.get_accounts()
                        if a.get_name() == acct_name
                    ),
                    None,
                )
                if account is None:
                    if session_is_logged_out(scraper.driver):
                        raise BofASessionLost(
                            "The overview page is logged out."
                        )
                    logger.error(
                        "Account %r disappeared from the overview page; "
                        "skipping.",
                        acct_name,
                    )
                    any_error = True
                    continue

                sess = scraper.open_account(account)
                try:
                    for _ in range(load_more):
                        try:
                            sess.load_more_transactions()
                        except NoSuchElementException:
                            break  # no "view more" button left
                    sess.scrape_transactions()
                    if not hasattr(sess, "get_transaction_details"):
                        raise click.ClickException(
                            "This bofa_scraper has no "
                            "get_transaction_details(); version >= 1.1.0 "
                            "is required."
                        )
                    fetched, failed, skipped = harvest_account(
                        sess,
                        account,
                        vocab,
                        details_log,
                        load_more=load_more,
                        delay=delay,
                        max_details=max_details,
                        stop_after_no_new=stop_after_no_new,
                        wedge_threshold=wedge_threshold,
                        wedge_cooldown=wedge_cooldown,
                        max_recoveries=max_recoveries,
                        batch_size=batch_size,
                        batch_pause=batch_pause,
                        seen_merchants=seen_merchants,
                        processed=processed,
                        console=console,
                        interactive=interactive,
                    )
                    total_fetched += fetched
                    total_failed += failed
                    total_skipped += skipped
                    harvested_names.append(acct_name)
                    harvest_state.accounts_seen.append(acct_name)
                finally:
                    sess.close()
            except click.ClickException:
                raise
            except BofASessionLost as e:
                if interactive:
                    console.print(f"[error]{e}[/error]")
                logger.error(
                    "BofA terminated the session; stopping the run and "
                    "writing partial results."
                )
                any_error = True
                break
            except (WebDriverException, Exception) as e:
                if interactive:
                    console.print(
                        f"[error]Failed to harvest {acct_name!r}: {e}[/error]"
                    )
                else:
                    logger.error("Failed to harvest %r: %s", acct_name, e)
                any_error = True
                # If the browser/geckodriver process itself is gone,
                # every remaining account would fail the same way.
                msg = str(e)
                if "Connection refused" in msg or "Max retries exceeded" in msg:
                    logger.error(
                        "Browser appears to be gone; aborting remaining "
                        "accounts."
                    )
                    break
                continue

    except KeyboardInterrupt:
        # Partial results are still worth writing out.
        logger.warning("Interrupted; writing partial results.")
        any_error = True
    finally:
        scraper.quit()

    # --- Persist the accumulator first (most important artifact) ---
    save_state(state, harvest_state, datetime.now(UTC))

    # --- Write the review YAML from the full accumulated vocabulary ---
    entries = build_review_entries(vocab)
    write_review_yaml(
        output, entries, sorted(set(harvest_state.accounts_seen)), harvested_at
    )

    # --- Append newly-fetched details to the details log (accumulates) ---
    if save_details is not None and details_log is not None:
        existing: list[dict[str, Any]] = []
        if save_details.exists():
            try:
                existing = json.loads(save_details.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                logger.warning(
                    "Could not read existing %s; overwriting.", save_details
                )
        save_details.write_text(
            json.dumps(existing + details_log, indent=2), encoding="utf-8"
        )

    if interactive:
        table = Table(title="Harvest summary", show_header=False)
        table.add_column("Metric", style="bold")
        table.add_column("Value", justify="right")
        table.add_row(
            "Accounts harvested (this run)", str(len(harvested_names))
        )
        table.add_row("Detail fetches (this run)", str(total_fetched))
        table.add_row("Failed fetches (this run)", str(total_failed))
        table.add_row("Skipped (known merchant)", str(total_skipped))
        table.add_row("Transactions processed (total)", str(len(processed)))
        table.add_row("Distinct categories (total)", str(len(entries)))
        for match, label in (
            ("exact", "  exact matches"),
            ("subname", "  sub-name matches"),
            ("create", "  new (would create)"),
        ):
            n = sum(1 for e in entries if e["match"] == match)
            table.add_row(label, str(n))
        console.print()
        console.print(table)
        console.print(f"[success]State saved → {state}[/success]")
        console.print(f"[success]Review file written → {output}[/success]")
        if save_details is not None:
            console.print(f"[dim]Details saved → {save_details}[/dim]")
    else:
        logger.info(
            "Run: %d fetches, %d failed, %d skipped over %d account(s). "
            "Totals: %d categories, %d transactions processed. "
            "State -> %s; review -> %s",
            total_fetched,
            total_failed,
            total_skipped,
            len(harvested_names),
            len(entries),
            len(processed),
            state,
            output,
        )

    if any_error:
        raise SystemExit(1)


########################################################################
########################################################################
#
def cli() -> None:
    """Load importer env vars from .env and invoke the CLI."""
    load_importer_env()
    cli_cmd()


if __name__ == "__main__":
    cli()
