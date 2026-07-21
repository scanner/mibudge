"""
TransactionCategory string resolution.

Category references cross the API and data-file boundaries as strings
-- full names like 'Food & Drink : Groceries'.  Provider vocabularies
never reach this layer: an importer translates its provider's category
strings (e.g. what the BofA scraper reports) into mibudge full names
before submitting, so mibudge carries no provider mappings.

Operations:
    normalize_category(raw)
        Split a raw category string into a normalized (group, name)
        pair: split on the FIRST colon, strip each side, collapse
        internal whitespace.  A string with no colon is a single-level
        category and maps to group == name.

    find_category_for_user(user, raw)
        Resolve a full-name string among the categories VISIBLE to a
        user (global rows plus own/shared custom rows).  Used by API
        input paths (e.g. the transaction-details action).  Never
        creates anything: an unknown name resolves to None and the
        caller decides how to report it.

    resolve_category_string(raw)
        Resolve a category string from one of mibudge's OWN data files
        (export/import).  Matches global rows and auto-creates a
        global row for an unknown pair so a restore never drops data.
        Accepts the legacy enum form ('Group:Name') including the few
        enum values whose canonical row is spelled differently
        (ENUM_SPELLING_CHANGES).

importers/bofa_categories.py mirrors the normalization rules (the
importers run standalone, without Django); keep the two in sync.
"""

# system imports
import logging
from typing import Any

# 3rd party imports
from django.db import IntegrityError
from django.db import transaction as db_transaction

# Project imports
from moneypools.models import TransactionCategory

logger = logging.getLogger("moneypools.service.categories")

# Legacy enum values whose canonical seeded row is spelled
# differently.  Keys are casefolded normalized (group, name) pairs;
# values are the canonical seeded pair.  The conversion migrations
# (0039/0040) carry inlined copies -- migrations must not import
# application code.
ENUM_SPELLING_CHANGES: dict[tuple[str, str], tuple[str, str]] = {
    ("food & drink", "alcohol & bars"): ("Food & Drink", "Alcohol"),
    ("transportation", "taxies"): ("Transportation", "Taxis & Rideshare"),
}


########################################################################
########################################################################
#
def normalize_category(raw: str) -> tuple[str, str]:
    """Split a raw category string into (group, name).

    Split on the FIRST colon, strip each side, collapse internal
    whitespace.  A string with no colon is a single-level category and
    maps to group == name.

    Args:
        raw: The category string
            (e.g. 'Food & Drink : Groceries', 'Education: Tuition & Fees').

    Returns:
        A normalized (group, name) tuple.
    """
    group, sep, name = raw.partition(":")
    group = " ".join(group.split())
    if not sep:
        return group, group
    name = " ".join(name.split())
    return group, name or group


########################################################################
########################################################################
#
def find_category_for_user(user: Any, raw: str) -> TransactionCategory | None:
    """Resolve a full-name string among the categories visible to a user.

    Matches case-insensitively on the normalized (group, name) pair.
    When both a global row and a visible custom row hold the same
    pair, the global row wins (API callers submitting canonical names
    mean the shared row).  Never creates anything.

    Args:
        user: The requesting user; determines the visible set.
        raw: The category full-name string.

    Returns:
        The matching TransactionCategory, or None when the string is
        blank or matches nothing visible.
    """
    group, name = normalize_category(raw)
    if not group:
        return None
    matches = list(
        TransactionCategory.objects.visible_to(user).filter(
            group__iexact=group, name__iexact=name
        )[:2]
    )
    if not matches:
        return None
    for category in matches:
        if category.owner_id is None:
            return category
    return matches[0]


########################################################################
########################################################################
#
def resolve_category_string(raw: str) -> TransactionCategory | None:
    """Resolve a category string from one of mibudge's own data files.

    Matches the normalized pair against global rows (case-insensitive,
    after applying ENUM_SPELLING_CHANGES for legacy enum-era files)
    and auto-creates a global row for an unknown pair -- an import
    must never drop category data.

    Args:
        raw: The category string from an export file.

    Returns:
        The resolved (or newly created) TransactionCategory, or None
        when the string is blank.
    """
    group, name = normalize_category(raw)
    if not group:
        return None
    changed = ENUM_SPELLING_CHANGES.get((group.casefold(), name.casefold()))
    if changed is not None:
        group, name = changed

    globals_qs = TransactionCategory.objects.filter(owner__isnull=True)

    category = globals_qs.filter(group__iexact=group, name__iexact=name).first()
    if category is not None:
        return category

    try:
        with db_transaction.atomic():
            category = TransactionCategory.objects.create(
                group=group, name=name
            )
        logger.info(
            "Auto-created global transaction category %r", category.full_name
        )
        return category
    except IntegrityError:
        # A concurrent resolution created the same pair between our
        # lookup and the insert; fetch the winner.
        return globals_qs.get(group__iexact=group, name__iexact=name)
