"""
BofA category vocabulary -> mibudge category translation.

Provider category mappings live with the importer, on this side of
the REST-API line: mibudge only ever sees category FULL NAMES from
its own canonical set ('{group} : {name}'), submitted with each
transaction-details item.  This module owns the translation for the
Bank of America scraper vocabulary.

Three layers:

* ``BOFA_CATEGORY_MAP`` -- the built-in reviewed mapping, covering
  every category string BofA has been observed to use.  A ``None``
  value means "deliberately leave the transaction unassigned" (the
  user categorizes it; e.g. BofA's own 'Uncategorized').
* An optional OVERLAY map (``load_overlay_map``) from importer
  config -- the same key/value shape, merged over the built-ins.
  This is how a newly discovered BofA category gets mapped without a
  code release: run the importer, note the unmapped categories it
  reports, add them to the overlay file.
* ``category_for`` -- the lookup the importers call per transaction.
  Unknown strings translate to no category AND are flagged so the
  caller can report them at end of run.

Keys are normalized provider strings: split on the first colon,
whitespace collapsed, casefolded, rejoined as ``'group:name'``
(``category_key``).  Overlay files use the same key form::

    # bofa-category-overlay.yaml
    'shopping & entertainment:sporting goods': 'Sports & Fitness : Sporting Goods'
    'some new bofa category:thing': null   # map to unassigned

Map VALUES are mibudge full names from the canonical global base set
(migration moneypools/0038); full names are the stable category
identity across deployments.
"""

# system imports
from dataclasses import dataclass
from pathlib import Path

# 3rd party imports
import yaml


####################################################################
#
def normalize_category(raw: str) -> tuple[str, str]:
    """Split a provider category string into (group, name).

    Split on the FIRST colon, strip each side, collapse internal
    whitespace.  A string with no colon is a single-level category
    and maps to group == name.  Mirrors
    moneypools.service.categories.normalize_category (inlined: the
    importers run standalone, without Django).

    Args:
        raw: The provider's category string
            (e.g. 'Groceries : Groceries').

    Returns:
        A normalized (group, name) tuple.
    """
    group, sep, name = raw.partition(":")
    group = " ".join(group.split())
    if not sep:
        return group, group
    name = " ".join(name.split())
    return group, name or group


####################################################################
#
def category_key(raw: str) -> str:
    """Build the normalized map key for a provider category string.

    Args:
        raw: The provider's category string.

    Returns:
        The casefolded 'group:name' key.
    """
    group, name = normalize_category(raw)
    return f"{group}:{name}".casefold()


# The reviewed BofA vocabulary (complete as of the 2026-07 harvest:
# 24 categories across 4 accounts, converged).  None = deliberately
# unassigned.
#
BOFA_CATEGORY_MAP: dict[str, str | None] = {
    "cash, checks & misc:checks": "Uncategorized : Checks",
    "cash, checks & misc:other bills": "Financial : Other Financial",
    "cash, checks & misc:other expenses": "Personal : Other Personal",
    "finance:credit card payments": "Financial : Credit Card Payment",
    "giving:giving": "Gifts & Donations : Charities",
    "groceries:groceries": "Food & Drink : Groceries",
    "health:healthcare/medical": "Health & Medical : Other Health & Medical",
    "home & utilities:cable/satellite services": "Utilities : Cable",
    "home & utilities:mortgages": "Home : Mortgage",
    "home & utilities:telephone services": "Utilities : Phone",
    "home & utilities:utilities": "Utilities : Other Utilities",
    "income:deposits": "Income : Other Income",
    "income:interest": "Income : Interest",
    "income:paychecks/salary": "Income : Paycheck",
    # Known-insurance, unknown domain (auto/health/home/life all
    # possible) -> the triage bucket; overlay-map to a domain row for
    # a deployment where one kind dominates.
    "insurance:insurance": "Uncategorized : Insurance",
    "restaurants & dining:restaurants/dining": "Food & Drink : Restaurants",
    "savings & transfers:savings": "Financial : Money Transfers",
    "savings & transfers:transfers": "Financial : Money Transfers",
    # Mostly computer/network gear; appliance purchases are
    # hand-recategorized to 'Home : Appliances' (a category map
    # cannot tell a switch from a fridge -- the MCC could, via
    # future auto-allocation rules).
    "shopping & entertainment:electronics": "Technology : Hardware",
    "shopping & entertainment:general merchandise": (
        "Uncategorized : Other Shopping"
    ),
    "shopping & entertainment:hobbies": "Personal : Hobbies",
    "transportation:gasoline/fuel": "Transportation : Gas",
    "travel:travel": "Travel : Other Travel",
    "uncategorized:uncategorized": "Uncategorized : Unknown",
}


########################################################################
########################################################################
#
@dataclass(frozen=True)
class CategoryLookup:
    """Result of translating one provider category string.

    `full_name` is the mibudge category to submit (None = leave the
    transaction unassigned).  `known` distinguishes a deliberate
    None-mapping from a vocabulary miss: False means the string is in
    neither the built-in map nor the overlay and should be surfaced
    in the importer's end-of-run report.
    """

    full_name: str | None
    known: bool


####################################################################
#
def load_overlay_map(path: Path) -> dict[str, str | None]:
    """Load an overlay mapping file.

    Args:
        path: YAML file mapping category_key strings to mibudge full
            names (or null for "leave unassigned").

    Returns:
        The overlay dict with normalized keys.

    Raises:
        ValueError: The file is not a flat mapping of strings.
    """
    data = yaml.safe_load(path.read_text())
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(
            f"{path}: expected a mapping, got {type(data).__name__}"
        )
    overlay: dict[str, str | None] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not (
            value is None or isinstance(value, str)
        ):
            raise ValueError(
                f"{path}: entries must map a category string to a "
                f"full name or null (bad entry: {key!r}: {value!r})"
            )
        overlay[category_key(key)] = value
    return overlay


####################################################################
#
def category_for(
    raw: str,
    overlay: dict[str, str | None] | None = None,
) -> CategoryLookup:
    """Translate a provider category string to a mibudge category.

    The overlay wins over the built-in map.

    Args:
        raw: The provider's category string (may be empty).
        overlay: Optional overlay mapping (see load_overlay_map).

    Returns:
        A CategoryLookup; known=False marks a vocabulary miss.
    """
    key = category_key(raw)
    if not key.strip(":"):
        return CategoryLookup(full_name=None, known=True)
    if overlay and key in overlay:
        return CategoryLookup(full_name=overlay[key], known=True)
    if key in BOFA_CATEGORY_MAP:
        return CategoryLookup(full_name=BOFA_CATEGORY_MAP[key], known=True)
    return CategoryLookup(full_name=None, known=False)
