"""
Transaction-details enrichment service.

Live bank scrapers can fetch per-transaction detail records (merchant
name, location, MCC, the bank's category hint, virtual card number)
for posted transactions.  This module applies one such raw detail
dict to a Transaction:

* the raw dict is stored verbatim in `Transaction.details` for
  provenance (NULL details == "never enriched"),
* merchant identity fields are extracted into queryable columns, with
  a cleanup pass (service/merchant_enrichment.py) that recovers the
  real store behind a payment-platform prefix (Square, Toast,
  DoorDash, ...) or extends a truncated provider-resolved name,
* the provider's location string is parsed into structured
  city/region/country columns (location fields are only written when
  currently empty -- user-entered values always win),
* the caller-supplied category (importers translate their provider's
  vocabulary into a mibudge category before submitting; mibudge
  carries no provider mappings) seeds `Transaction.category` (and the
  transaction's still-NULL allocations) when unassigned,
* on first enrichment the display `description` is recomposed unless
  the user has edited it.

MCC policy: any 4-digit code is stored -- the provider's data is
authoritative and the iso18245 package can lag the card networks'
registries -- so iso18245 lookups only ever produce warnings, never
failures.  Malformed (non ^\\d{4}$) values are not stored in the
column; the raw value survives in the details JSON.

Invoked from the `BankAccountViewSet.transaction_details` REST
action.
"""

# system imports
import logging
import re
from typing import Any

# 3rd party imports
import iso18245
from django.db import transaction as db_transaction

# Project imports
from moneypools.description_utils import compose_enriched_description
from moneypools.models import (
    Transaction,
    TransactionAllocation,
    TransactionCategory,
)
from moneypools.service import merchant_enrichment as merchant_enrichment_svc

logger = logging.getLogger("moneypools.service.transaction_details")

# Per-item statuses returned by apply_details (plus NOT_FOUND, which
# only the REST action can produce -- it resolves the transaction).
#
STATUS_APPLIED = "applied"
STATUS_SKIPPED_HAS_DETAILS = "skipped_has_details"
STATUS_SKIPPED_PENDING = "skipped_pending"
STATUS_NOT_FOUND = "not_found"

# "CITY, ST" -- the only structured location format observed from
# BofA's merchant_information field.  Anything else is stored
# verbatim as the city.
#
_CITY_REGION_RE = re.compile(r"^(?P<city>.+?),\s*(?P<region>[A-Z]{2})$")

_MCC_RE = re.compile(r"^\d{4}$")


########################################################################
########################################################################
#
def parse_merchant_information(
    raw: str,
) -> tuple[str | None, str | None, str | None]:
    """Parse a provider merchant-location string into structured parts.

    BofA renders merchant locations as 'CITY, ST' (two-letter US
    state).  That form parses into (city, region, 'US').  Any other
    non-empty string is kept verbatim as the city with no
    region/country -- the raw value also survives in the details
    JSON, so nothing is lost if this heuristic mis-fires.

    Args:
        raw: The provider's merchant location string.

    Returns:
        A (city, region, country) tuple; each element may be None.
    """
    info = " ".join(raw.split())
    if not info:
        return None, None, None
    m = _CITY_REGION_RE.match(info)
    if m:
        # rstrip: a space before the comma ("CITY , ST") would
        # otherwise survive in the captured city.
        return m.group("city").rstrip(), m.group("region"), "US"
    return info, None, None


####################################################################
#
def _clean_str(
    value: Any,
    max_length: int,
    field: str,
    warnings: list[str],
) -> str | None:
    """Normalize a raw detail value into a column-safe string.

    Collapses whitespace and truncates to the column width (with a
    warning) so a provider's oversized value can never fail the whole
    request.

    Args:
        value: The raw value from the details dict.
        max_length: The destination column's max_length.
        field: Field name used in the truncation warning.
        warnings: Warning accumulator, appended to in place.

    Returns:
        The cleaned string, or None when the value is empty/absent.
    """
    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    if not cleaned:
        return None
    if len(cleaned) > max_length:
        warnings.append(
            f"{field} truncated to {max_length} characters (got {len(cleaned)})"
        )
        cleaned = cleaned[:max_length]
    return cleaned


####################################################################
#
def _extract_mcc(value: Any, warnings: list[str]) -> str | None:
    """Apply the MCC storage policy to a raw merchant_category_code.

    Any ^\\d{4}$ code is stored; iso18245 is consulted only to WARN
    about codes missing from (or invalid per) its registry, because
    the provider's data is authoritative and the package lags the
    card networks.  Malformed values are not stored (the raw value
    remains in the details JSON).

    Args:
        value: The raw MCC value from the details dict.
        warnings: Warning accumulator, appended to in place.

    Returns:
        The 4-digit code to store, or None.
    """
    if value is None:
        return None
    code = str(value).strip()
    if not code:
        return None
    if not _MCC_RE.match(code):
        warnings.append(
            f"merchant_category_code {code!r} is not a 4-digit MCC; "
            "not stored (raw value kept in details)"
        )
        return None
    try:
        iso18245.get_mcc(code)
    except (iso18245.MCCNotFound, iso18245.InvalidMCC):
        warnings.append(
            f"MCC {code} is not in the iso18245 registry; stored anyway"
        )
    return code


########################################################################
########################################################################
#
def apply_details(
    tx: Transaction,
    raw: dict[str, Any],
    category: TransactionCategory | None = None,
    overwrite: bool = False,
    recompose_description: bool = False,
) -> tuple[str, list[str]]:
    """Apply one raw provider details dict to a Transaction.

    See the module docstring for the full semantics.  Notable rules:

    * Pending rows are never enriched (details exist only for posted
      transactions; a pending row's UUID is not even stable).
    * A row with details already present is skipped unless
      `overwrite` -- and even then, location fields and an assigned
      category are never clobbered.
    * Category seeding fires only when `tx.category` is NULL, and
      then also backfills the transaction's allocations whose
      category is still NULL.  Without that backfill the "allocation
      copies the transaction category at creation" rule would never
      fire for scraped transactions -- their default allocation
      exists before details arrive.  This is initial seeding only,
      never edit propagation.
    * The display description is recomposed on first enrichment, or
      on a later `overwrite` when `recompose_description` is also set
      -- both gated on the user not having edited it.
      `recompose_description` defaults off so a routine importer
      overwrite (re-applying a fresher scrape) does not churn a
      description the user has come to expect; the
      reenrich_merchant_identity management command sets it because
      refreshing stale display text for historical rows is its entire
      purpose.

    Args:
        tx: The Transaction to enrich.
        raw: The provider's raw details dict (stored verbatim).
        category: The already-resolved category to seed, or None.  The
            caller resolves the importer-supplied full name (see
            service.categories.find_category_for_user).
        overwrite: Re-apply scraper-owned fields over an existing
            enrichment.
        recompose_description: Also recompose the description on an
            `overwrite` pass (not just first enrichment).

    Returns:
        A (status, warnings) tuple; status is one of the STATUS_*
        constants (never NOT_FOUND).
    """
    if tx.pending:
        return STATUS_SKIPPED_PENDING, []
    if tx.details is not None and not overwrite:
        return STATUS_SKIPPED_HAS_DETAILS, []

    warnings: list[str] = []
    first_enrichment = tx.details is None

    with db_transaction.atomic():
        tx.details = raw

        tx.merchant_name = _clean_str(
            raw.get("merchant_name"), 128, "merchant_name", warnings
        )

        # Merchant identity cleanup (service/merchant_enrichment.py):
        # detect a known payment-platform prefix and recover the real
        # store behind it, or -- for direct purchases -- try
        # extend-only DBA-name recovery from the raw description (e.g.
        # BofA's "COSTCO" -> "COSTCO GAS").  Always recomputed from raw
        # so an overwrite re-derives it fresh.
        intermediary = merchant_enrichment_svc.split_intermediary(
            tx.merchant_name, tx.raw_description
        )
        if intermediary is not None:
            tx.merchant_intermediary = intermediary.token
            if intermediary.store_name:
                tx.merchant_name = _clean_str(
                    intermediary.store_name, 128, "merchant_name", warnings
                )
        else:
            tx.merchant_intermediary = None
            refined = merchant_enrichment_svc.refine_merchant_name(
                tx.merchant_name, tx.raw_description
            )
            tx.merchant_name = _clean_str(
                refined, 128, "merchant_name", warnings
            )

        tx.merchant_category = _clean_str(
            raw.get("merchant_category"), 128, "merchant_category", warnings
        )
        tx.merchant_category_code = _extract_mcc(
            raw.get("merchant_category_code"), warnings
        )
        tx.virtual_card_number = _clean_str(
            raw.get("virtual_card_number"),
            32,
            "virtual_card_number",
            warnings,
        )

        info = raw.get("merchant_information")
        if info is not None:
            city, region, country = parse_merchant_information(str(info))
            if city and not tx.merchant_city:
                tx.merchant_city = _clean_str(
                    city, 128, "merchant_city", warnings
                )
            if region and not tx.merchant_region:
                tx.merchant_region = region
            if country and not tx.merchant_country:
                tx.merchant_country = country

        if category is not None and tx.category is None:
            tx.category = category
            TransactionAllocation.objects.filter(
                transaction=tx, category__isnull=True
            ).update(category=category)

        if (
            first_enrichment or recompose_description
        ) and not tx.description_user_edited:
            composed = compose_enriched_description(
                merchant_name=tx.merchant_name,
                city=tx.merchant_city,
                region=tx.merchant_region,
                merchant_category=tx.merchant_category,
                intermediary_display_name=(
                    intermediary.display_name
                    if intermediary is not None
                    else None
                ),
            )
            if composed:
                tx.description = composed

        tx.save()

    logger.info(
        "Applied transaction details to %s (%s warnings)",
        tx.id,
        len(warnings),
    )
    return STATUS_APPLIED, warnings
