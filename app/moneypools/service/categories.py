"""
TransactionCategory resolution service.

Providers (bank scrapers, importers, export files) supply category
hints as raw strings like 'Groceries : Groceries' or
'Food & Drink:Restaurants'.  This module normalizes those strings and
resolves them to TransactionCategory rows.

Operations:
    normalize_category(raw)
        Split a raw category string into a normalized (group, name)
        pair: split on the FIRST colon, strip each side, collapse
        internal whitespace.  A string with no colon is a single-level
        category and maps to group == name.

    resolve_category_string(raw)
        Resolve a raw string to a TransactionCategory using the
        non-alias rules: (1) exact full-name match on global rows,
        (2) unique sub-name match GUARDED by "the name is not also an
        existing group name", (3) auto-create a global row.  Used by
        import_bank_account and as the fallback for provider
        resolution.

    resolve_provider_category(provider, raw)
        Full provider resolution: alias-table lookup FIRST, then
        resolve_category_string.  Every successful non-alias
        resolution writes an alias row, so a bad auto-mapping can be
        re-pointed in the django-admin without touching transaction
        data.

The sub-name guard exists because BofA renders single-level categories
as 'X : X' -- without the guard, BofA's 'Travel : Travel' would
uniquely sub-name match 'Business:Travel' instead of creating the
intended top-level 'Travel : Travel' category.

The dry-run mirror of these rules lives in
importers/harvest_bofa_categories.py (which runs standalone on the
scraping host); keep the two in sync when changing resolution order.
"""

# system imports
import logging

# 3rd party imports
from django.db import IntegrityError
from django.db import transaction as db_transaction

# Project imports
from moneypools.models import TransactionCategory, TransactionCategoryAlias

logger = logging.getLogger("moneypools.service.categories")


########################################################################
########################################################################
#
def normalize_category(raw: str) -> tuple[str, str]:
    """Split a raw provider category string into (group, name).

    Split on the FIRST colon, strip each side, collapse internal
    whitespace.  A string with no colon is a single-level category and
    maps to group == name.

    Args:
        raw: The provider's category string
            (e.g. 'Groceries : Groceries', 'Education: Tuition & Fees').

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
def resolve_category_string(raw: str) -> TransactionCategory | None:
    """Resolve a raw category string to a TransactionCategory.

    Applies the non-alias resolution rules, in order:

    1. Exact full-name match on global rows (case-insensitive on both
       group and name).
    2. Unique sub-name match on global rows, GUARDED by "the name is
       not also an existing global group name" -- without the guard,
       BofA's single-level 'Travel : Travel' would mis-map to
       'Business:Travel'.
    3. Auto-create a global row for the normalized pair.

    Args:
        raw: The raw category string.

    Returns:
        The resolved (or newly created) TransactionCategory, or None
        when the string is blank.
    """
    group, name = normalize_category(raw)
    if not group:
        return None

    globals_qs = TransactionCategory.objects.filter(owner__isnull=True)

    category = globals_qs.filter(group__iexact=group, name__iexact=name).first()
    if category is not None:
        return category

    sub_matches = list(globals_qs.filter(name__iexact=name)[:2])
    if len(sub_matches) == 1:
        name_is_group = globals_qs.filter(group__iexact=name).exists()
        if not name_is_group:
            return sub_matches[0]

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


########################################################################
########################################################################
#
def resolve_provider_category(
    provider: str, raw: str
) -> TransactionCategory | None:
    """Resolve a provider's raw category string to a TransactionCategory.

    The alias table is consulted FIRST so that reviewed mappings (and
    admin corrections of earlier auto-mappings) always win.  On an
    alias miss the string is resolved via resolve_category_string and
    the result is remembered as a new alias row.

    Args:
        provider: The provider key (e.g. 'bofa').
        raw: The provider's raw category string.

    Returns:
        The resolved TransactionCategory, or None when the string is
        blank.
    """
    group, name = normalize_category(raw)
    if not group:
        return None
    key = alias_key(group, name)

    alias = (
        TransactionCategoryAlias.objects.select_related("category")
        .filter(provider=provider, alias_key=key)
        .first()
    )
    if alias is not None:
        return alias.category

    category = resolve_category_string(raw)
    if category is None:
        return None

    # Remember the resolution so a bad auto-mapping can be re-pointed
    # in the admin.  get_or_create absorbs a concurrent writer.
    TransactionCategoryAlias.objects.get_or_create(
        provider=provider,
        alias_key=key,
        defaults={"category": category},
    )
    return category
