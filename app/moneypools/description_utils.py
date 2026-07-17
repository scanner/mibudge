"""
Utilities for extracting structured data from raw bank transaction descriptions.

parse_transaction_date -- derive the purchase date embedded in a description.
compose_enriched_description -- build a display description from
    merchant-detail columns.
"""

# system imports
#
import re
from datetime import date

# MM/DD purchase date embedded in most card-network descriptions
# (e.g. "TST*CAFE BORRONE 03/28 MOBILE PURCHASE").
#
_DESC_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})\b")


####################################################################
#
def parse_transaction_date(
    raw_description: str,
    posted_date: date,
    max_days_before: int = 7,
) -> date:
    """Derive the purchase date from a raw bank description.

    Card networks embed the actual purchase date as an MM/DD pattern
    (e.g. ``TST*CAFE BORRONE 03/28 MOBILE PURCHASE``).  This date is
    typically a few days before the bank's settlement / posted date.

    Args:
        raw_description: Unedited description string from the bank feed.
        posted_date: The bank-supplied settlement date.  Used to resolve
            the year and as the fallback when no date can be parsed.
        max_days_before: Maximum number of days the parsed date may
            precede ``posted_date``.  Parsed dates outside the window
            ``[posted_date - max_days_before, posted_date]`` are
            discarded and the fallback is used instead.

    Returns:
        The parsed purchase date, or ``posted_date`` when no parseable
        date is found or the parsed date falls outside the sanity window.
    """
    m = _DESC_DATE_RE.search(raw_description)
    if not m:
        return posted_date

    month = int(m.group(1))
    day = int(m.group(2))

    # Resolve year: try the posted_date's year first; if the resulting
    # date is after posted_date, try the previous year (handles the
    # December purchase / January settlement wrap-around).
    #
    try:
        candidate = date(posted_date.year, month, day)
    except ValueError:
        return posted_date

    if candidate > posted_date:
        try:
            candidate = date(posted_date.year - 1, month, day)
        except ValueError:
            return posted_date

    delta = (posted_date - candidate).days
    if 0 <= delta <= max_days_before:
        return candidate

    return posted_date


####################################################################
#
def compose_enriched_description(
    merchant_name: str | None,
    city: str | None,
    region: str | None,
    merchant_category: str | None,
) -> str:
    """Compose a display description from merchant-detail columns.

    Produces strings like
    'Trader Joes -- Menlo Park, CA (Grocery Stores and Supermarkets)',
    omitting any empty part: the location clause drops missing
    city/region components, and the parenthesised category is skipped
    entirely when absent.

    Args:
        merchant_name: The merchant's display name.
        city: The merchant location city.
        region: The merchant location region (state/province).
        merchant_category: The provider's human-readable MCC
            description.

    Returns:
        The composed description, or '' when every part is empty
        (callers should keep the existing description in that case).
    """
    location = ", ".join(p for p in (city, region) if p)
    head = " -- ".join(p for p in (merchant_name, location) if p)
    if merchant_category:
        if head:
            return f"{head} ({merchant_category})"
        return merchant_category
    return head
