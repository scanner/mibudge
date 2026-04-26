"""
Utilities for extracting structured data from raw bank transaction descriptions.

parse_transaction_date -- derive the purchase date embedded in a description.
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
