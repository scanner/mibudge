"""
Merchant name and identity cleanup.

Card-network raw descriptions are a muddy source: payment platforms
(Square, Toast, DoorDash, ...) hide the real store behind a "soft
descriptor" prefix, and even a provider's own resolved merchant name
can be truncated or rolled up in a way that erases a distinction that
matters (BofA collapses "COSTCO GAS #10" and "COSTCO WHSE #123" down
to plain "COSTCO"). This module is the deliberate home for that
muddiness -- it is expected to keep growing rules as more of it gets
observed, and is the natural place to eventually plug in the (name,
MCC)-keyed Merchant model's identity resolution, or an LLM-assisted
fallback for names the regex/pattern approach cannot untangle. Keeping
it isolated here means that growth does not leak into
service/transaction_details.py, which only orchestrates.

Two independent operations, both keyed off Transaction.raw_description
(provider-neutral -- the literal card-network string, unlike a
provider's own category vocabulary, which importers translate before
it ever reaches mibudge; see service/categories.py):

    split_intermediary(details_merchant_name, raw_description)
        Detect a known payment-platform prefix (MerchantIntermediaryPattern,
        admin-editable) and recover the store name behind it.

    refine_merchant_name(details_name, search_text)
        Extend-only DBA-name recovery: if raw_description's
        noise-stripped text starts with (and extends) the provider's
        resolved name, use the extended form. Never replaces a name
        the remainder does not start with.
"""

# system imports
import re
from dataclasses import dataclass

# Project imports
from moneypools.models import MerchantIntermediaryPattern

# MM/DD purchase date embedded in most card-network descriptions --
# everything from here to the end of the string is transaction-type /
# location noise ("MOBILE PURCHASE Palo Alto CA"), not part of the name.
_DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}\b")

# A trailing store number ("COSTCO GAS #10") left over after date
# stripping.
_STORE_NUMBER_RE = re.compile(r"\s*#\d+\s*$")


########################################################################
########################################################################
#
@dataclass(frozen=True)
class IntermediaryMatch:
    """Result of a successful intermediary-pattern match."""

    token: str
    display_name: str
    store_name: str | None


####################################################################
#
def _compiled_patterns() -> tuple[tuple[re.Pattern, str, str], ...]:
    """Active MerchantIntermediaryPattern rows, compiled and ordered."""
    return tuple(
        (re.compile(row.pattern, re.IGNORECASE), row.token, row.display_name)
        for row in MerchantIntermediaryPattern.objects.filter(
            active=True
        ).order_by("order")
    )


####################################################################
#
def _strip_known_noise(text: str) -> str:
    """Strip the trailing date/transaction-type/location tail.

    Truncates at the first embedded MM/DD date (the stable anchor
    every observed BofA descriptor tail starts with) and then drops a
    trailing store number ("COSTCO GAS #10" -> "COSTCO GAS").

    Args:
        text: Raw text to clean (a captured intermediary store name,
            or a full raw_description).

    Returns:
        The cleaned text, possibly empty.
    """
    m = _DATE_RE.search(text)
    if m:
        text = text[: m.start()]
    text = _STORE_NUMBER_RE.sub("", text)
    return " ".join(text.split())


########################################################################
########################################################################
#
def split_intermediary(
    details_merchant_name: str | None, raw_description: str
) -> IntermediaryMatch | None:
    """Detect a known payment-platform prefix and recover the store name.

    Matches are tried against `raw_description` (the authoritative
    card-network string) in pattern `order`; the first match wins. If
    the provider's own `details_merchant_name` does NOT also match the
    same prefix pattern, it has already been resolved by the provider
    (e.g. BofA's dialog turning "SQ *SHAKE SHACK" into "SHAKE SHACK")
    and is trusted as-is. Otherwise the store name is derived from the
    pattern's 'store' capture group and noise-stripped.

    Args:
        details_merchant_name: The provider's own resolved merchant
            name, or None.
        raw_description: The transaction's raw bank description.

    Returns:
        An IntermediaryMatch, or None when no pattern matches (a
        direct purchase -- caller should leave merchant_name /
        merchant_intermediary untouched).
    """
    for compiled, token, display_name in _compiled_patterns():
        m = compiled.match(raw_description)
        if not m:
            continue

        if details_merchant_name and not compiled.match(details_merchant_name):
            return IntermediaryMatch(token, display_name, details_merchant_name)

        captured = m.groupdict().get("store")
        store = _strip_known_noise(captured) if captured else ""
        return IntermediaryMatch(token, display_name, store or None)

    return None


########################################################################
########################################################################
#
def refine_merchant_name(
    details_name: str | None, search_text: str
) -> str | None:
    """Extend-only DBA-name recovery from raw description text.

    If the noise-stripped `search_text` starts with `details_name`
    (case-insensitive) and has MORE text, the extended form is
    returned ("COSTCO" -> "COSTCO GAS"). Never replaces a name the
    remainder does not start with -- warehouse runs stay "COSTCO WHSE"
    (the card network's registered DBA name; faithful, and the
    distinction is the point). Prettifying DBA names into display
    names is the future (name, MCC) Merchant model's job.

    Args:
        details_name: The provider's resolved merchant name, or None.
        search_text: Text to recover an extension from -- typically
            the transaction's raw_description for a direct purchase.

    Returns:
        The extended name, or `details_name` unchanged when no
        extension applies.
    """
    cleaned = _strip_known_noise(search_text)
    if not cleaned or not details_name:
        return details_name
    if cleaned.casefold().startswith(details_name.casefold()) and len(
        cleaned
    ) > len(details_name):
        return cleaned
    return details_name
