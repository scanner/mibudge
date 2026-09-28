#!/usr/bin/env python
#
"""
Tests for the transaction-details enrichment pipeline.

Covers the location parser, the description composition helper, the
apply_details service (MCC policy, caller-supplied category +
allocation seeding, location preservation, overwrite semantics), the
bank-account transaction-details REST action (including category
full-name resolution), the merchant filters, and the serializer's
writable/read-only split for merchant fields.
"""

# system imports
#
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

# 3rd party imports
#
import pytest
import pytest_check as check
from faker import Faker
from rest_framework.test import APIClient

# Project imports
#
from moneypools.description_utils import compose_enriched_description
from moneypools.models import BankAccount, Transaction, TransactionCategory
from moneypools.service import transaction_details as details_svc
from users.models import User

from .conftest import MerchantPlace

pytestmark = pytest.mark.django_db


########################################################################
####################################################################
#
@pytest.fixture
def bofa_details(
    merchant_place: MerchantPlace,
) -> Callable[..., dict[str, Any]]:
    """Factory building a details dict shaped like bofa_scraper output.

    The location is `merchant_place`, in BofA's 'CITY, ST' form.
    Keyword arguments override (or add) keys.
    """

    def _build(**overrides: Any) -> dict[str, Any]:
        details: dict[str, Any] = {
            "merchant_name": "Trader Joes",
            "merchant_information": (
                f"{merchant_place.city.upper()}, {merchant_place.region}"
            ),
            "merchant_category": "Grocery Stores and Supermarkets",
            "merchant_category_code": "5411",
            "transaction_category": "Dining : Restaurants",
            "virtual_card_number": "XXXX-XXXX-XXXX-1439",
            "phone_number": "800-555-0100",
        }
        details.update(overrides)
        return details

    return _build


########################################################################
####################################################################
#
@pytest.fixture
def posted_tx(
    account: BankAccount,
    transaction_factory: Callable[..., Transaction],
    merchant_place: MerchantPlace,
) -> Transaction:
    """A posted, never-enriched purchase at `merchant_place`."""
    return transaction_factory(
        bank_account=account,
        pending=False,
        posted_date=datetime(2026, 7, 10, tzinfo=UTC),
        raw_description=(
            "TRADER JOES 07/09 MOBILE PURCHASE "
            f"{merchant_place.city.upper()} {merchant_place.region}"
        ),
    )


########################################################################
####################################################################
#
@pytest.fixture
def dining_category(
    transaction_category_factory: Callable[..., TransactionCategory],
) -> TransactionCategory:
    """The global category the importer submits as 'Dining : Restaurants'."""
    return transaction_category_factory(group="Dining", name="Restaurants")


########################################################################
########################################################################
#
class TestParseMerchantInformation:
    """Tests for the provider location-string parser."""

    ################################################################
    #
    @pytest.mark.parametrize(
        "raw,expected",
        [
            # The BofA 'CITY, ST' form parses fully; whitespace is
            # collapsed before matching.
            ("  LAKE   HOLLOW ,  OR  ", ("LAKE HOLLOW", "OR", "US")),
            # Anything else lands verbatim in city with no
            # region/country -- a lowercase state code does not match
            # the 'CITY, ST' pattern.
            ("Springfield, il", ("Springfield, il", None, None)),
            # Empty input parses to nothing at all.
            ("   ", (None, None, None)),
        ],
    )
    def test_parse_table(
        self,
        raw: str,
        expected: tuple[str | None, str | None, str | None],
    ) -> None:
        """
        GIVEN: a provider merchant_information string
        WHEN:  parse_merchant_information is applied
        THEN:  the expected (city, region, country) tuple results
        """
        assert details_svc.parse_merchant_information(raw) == expected


########################################################################
########################################################################
#
class TestComposeEnrichedDescription:
    """Tests for the merchant-detail description composition."""

    ################################################################
    #
    @pytest.mark.parametrize(
        "name,city,region,category,expected",
        [
            # Every part missing in turn; the full composition is
            # covered end-to-end by TestApplyDetails.
            ("Trader Joes", None, None, None, "Trader Joes"),
            (
                "Trader Joes",
                "Lake Hollow",
                None,
                None,
                "Trader Joes -- Lake Hollow",
            ),
            (None, "Lake Hollow", "OR", None, "Lake Hollow, OR"),
            (None, None, None, "Groceries", "Groceries"),
            (
                "Trader Joes",
                None,
                None,
                "Groceries",
                "Trader Joes (Groceries)",
            ),
            # Nothing at all composes to '' (caller keeps the old
            # description).
            (None, None, None, None, ""),
        ],
    )
    def test_compose_table(
        self,
        name: str | None,
        city: str | None,
        region: str | None,
        category: str | None,
        expected: str,
    ) -> None:
        """
        GIVEN: a combination of merchant-detail columns
        WHEN:  compose_enriched_description is applied
        THEN:  empty parts are omitted from the composed string
        """
        assert (
            compose_enriched_description(
                merchant_name=name,
                city=city,
                region=region,
                merchant_category=category,
            )
            == expected
        )


########################################################################
########################################################################
#
class TestApplyDetails:
    """Tests for the apply_details service."""

    ################################################################
    #
    def test_full_enrichment(
        self,
        posted_tx: Transaction,
        dining_category: TransactionCategory,
        bofa_details: Callable[..., dict[str, Any]],
        merchant_place: MerchantPlace,
    ) -> None:
        """
        GIVEN: a posted, never-enriched transaction with an unassigned
               category and a default allocation
        WHEN:  a full BofA details dict is applied with a resolved
               category
        THEN:  the raw dict is stored verbatim, merchant columns are
               extracted, the category is seeded (and copied onto the
               NULL-category allocation), and the description is
               recomposed
        """
        raw = bofa_details()
        status, warnings = details_svc.apply_details(
            posted_tx, raw, category=dining_category
        )

        check.equal(status, details_svc.STATUS_APPLIED, "applied")
        check.equal(warnings, [], "without warnings")

        posted_tx.refresh_from_db()
        check.equal(posted_tx.details, raw, "raw dict stored verbatim")
        check.equal(
            (
                posted_tx.merchant_name,
                posted_tx.merchant_city,
                posted_tx.merchant_region,
                posted_tx.merchant_country,
                posted_tx.merchant_category,
                posted_tx.merchant_category_code,
                posted_tx.virtual_card_number,
            ),
            (
                "Trader Joes",
                merchant_place.city.upper(),
                merchant_place.region,
                "US",
                "Grocery Stores and Supermarkets",
                "5411",
                "XXXX-XXXX-XXXX-1439",
            ),
            "merchant columns extracted",
        )
        check.equal(
            posted_tx.category, dining_category, "transaction category seeded"
        )
        check.equal(
            posted_tx.allocations.get().category,
            dining_category,
            "and copied onto the NULL-category allocation",
        )
        check.equal(
            posted_tx.description,
            f"Trader Joes -- {merchant_place.city.upper()}, "
            f"{merchant_place.region} (Grocery Stores and Supermarkets)",
            "description recomposed",
        )

    ################################################################
    #
    def test_pending_row_skipped(
        self,
        account: BankAccount,
        transaction_factory: Callable[..., Transaction],
        bofa_details: Callable[..., dict[str, Any]],
    ) -> None:
        """
        GIVEN: a pending transaction
        WHEN:  details are applied
        THEN:  it is skipped as pending and left unenriched
        """
        tx = transaction_factory(bank_account=account, pending=True)

        status, warnings = details_svc.apply_details(tx, bofa_details())

        check.equal(status, details_svc.STATUS_SKIPPED_PENDING, "skipped")
        check.equal(warnings, [], "without warnings")
        tx.refresh_from_db()
        check.is_none(tx.details, "row untouched")

    ################################################################
    #
    def test_enriched_row_skipped_without_overwrite(
        self,
        posted_tx: Transaction,
        bofa_details: Callable[..., dict[str, Any]],
    ) -> None:
        """
        GIVEN: an already-enriched transaction
        WHEN:  different details are applied without overwrite
        THEN:  it is skipped as already enriched and keeps its values
        """
        details_svc.apply_details(posted_tx, bofa_details())

        status, warnings = details_svc.apply_details(
            posted_tx, bofa_details(merchant_name="Imposter Mart")
        )

        check.equal(status, details_svc.STATUS_SKIPPED_HAS_DETAILS, "skipped")
        check.equal(warnings, [], "without warnings")
        posted_tx.refresh_from_db()
        check.equal(posted_tx.merchant_name, "Trader Joes", "row untouched")

    ################################################################
    #
    def test_overwrite_replaces_scraper_owned_fields_only(
        self,
        posted_tx: Transaction,
        dining_category: TransactionCategory,
        transaction_category_factory: Callable[..., TransactionCategory],
        bofa_details: Callable[..., dict[str, Any]],
        merchant_place: MerchantPlace,
        faker: Faker,
    ) -> None:
        """
        GIVEN: an enriched transaction whose category was later changed
               by the user
        WHEN:  new details are applied with overwrite=True
        THEN:  scraper-owned fields update, but the assigned category,
               the location fields, and the composed description stay
        """
        details_svc.apply_details(
            posted_tx, bofa_details(), category=dining_category
        )
        posted_tx.refresh_from_db()
        original_description = posted_tx.description

        user_category = transaction_category_factory(
            group="Food & Drink", name="Snacks"
        )
        posted_tx.category = user_category
        posted_tx.save()

        status, _ = details_svc.apply_details(
            posted_tx,
            bofa_details(
                merchant_name="Trader Joes #123",
                merchant_information=(
                    f"{faker.unique.city().upper()}, {merchant_place.region}"
                ),
            ),
            category=dining_category,
            overwrite=True,
        )

        assert status == details_svc.STATUS_APPLIED
        posted_tx.refresh_from_db()
        check.equal(
            posted_tx.merchant_name,
            "Trader Joes #123",
            "scraper-owned column updated",
        )
        check.equal(
            posted_tx.merchant_city,
            merchant_place.city.upper(),
            "location from the first enrichment never clobbered",
        )
        check.equal(
            posted_tx.category, user_category, "user's category survives"
        )
        check.equal(
            posted_tx.description,
            original_description,
            "description recomposes only on first enrichment",
        )

    ################################################################
    #
    def test_recompose_description_forces_refresh_on_overwrite(
        self,
        posted_tx: Transaction,
        bofa_details: Callable[..., dict[str, Any]],
        merchant_place: MerchantPlace,
    ) -> None:
        """
        GIVEN: an enriched transaction with an unedited description
        WHEN:  overwrite is applied with recompose_description=True
        THEN:  the description DOES refresh (used by the
               reenrich_merchant_identity command to fix stale display
               text on historical rows)
        """
        details_svc.apply_details(posted_tx, bofa_details())
        posted_tx.refresh_from_db()

        details_svc.apply_details(
            posted_tx,
            bofa_details(merchant_name="Trader Joes #123"),
            overwrite=True,
            recompose_description=True,
        )

        posted_tx.refresh_from_db()
        check.is_in(
            "Trader Joes #123",
            posted_tx.description,
            "refreshed merchant name reaches the description",
        )
        check.is_in(
            merchant_place.city.upper(),
            posted_tx.description,
            "location unaffected (never clobbered by overwrite)",
        )

    ################################################################
    #
    def test_user_location_wins_over_enrichment(
        self,
        posted_tx: Transaction,
        bofa_details: Callable[..., dict[str, Any]],
        merchant_place: MerchantPlace,
        faker: Faker,
    ) -> None:
        """
        GIVEN: a transaction whose location was set by the user before
               enrichment ever ran
        WHEN:  details are applied
        THEN:  the user's location values are preserved and only the
               fields the user left empty are filled
        """
        user_city, user_address = faker.unique.city(), faker.street_address()
        posted_tx.merchant_city = user_city
        posted_tx.merchant_address = user_address
        posted_tx.save()

        status, _ = details_svc.apply_details(posted_tx, bofa_details())

        assert status == details_svc.STATUS_APPLIED
        posted_tx.refresh_from_db()
        check.equal(
            (posted_tx.merchant_city, posted_tx.merchant_address),
            (user_city, user_address),
            "user's location values preserved",
        )
        check.equal(
            (posted_tx.merchant_region, posted_tx.merchant_country),
            (merchant_place.region, "US"),
            "empty location fields filled",
        )

    ################################################################
    #
    def test_categorized_allocation_not_reseeded(
        self,
        posted_tx: Transaction,
        transaction_category_factory: Callable[..., TransactionCategory],
        dining_category: TransactionCategory,
        bofa_details: Callable[..., dict[str, Any]],
    ) -> None:
        """
        GIVEN: an uncategorized transaction whose allocation already has
               a category
        WHEN:  details are applied with a different category
        THEN:  the transaction's NULL category seeds; the categorized
               allocation is left alone
        """
        pre_set = transaction_category_factory()
        allocation = posted_tx.allocations.get()
        allocation.category = pre_set
        allocation.save()

        details_svc.apply_details(
            posted_tx, bofa_details(), category=dining_category
        )

        posted_tx.refresh_from_db()
        allocation.refresh_from_db()
        check.equal(
            posted_tx.category, dining_category, "transaction category seeded"
        )
        check.equal(allocation.category, pre_set, "allocation left alone")

    ################################################################
    #
    def test_categorized_transaction_not_reseeded(
        self,
        posted_tx: Transaction,
        transaction_category_factory: Callable[..., TransactionCategory],
        dining_category: TransactionCategory,
        bofa_details: Callable[..., dict[str, Any]],
    ) -> None:
        """
        GIVEN: a transaction that already has a category, with an
               uncategorized allocation
        WHEN:  details are applied with a different category
        THEN:  the transaction keeps its category, and since seeding did
               not fire the allocation is not backfilled either
        """
        pre_set = transaction_category_factory()
        posted_tx.category = pre_set
        posted_tx.save()

        details_svc.apply_details(
            posted_tx, bofa_details(), category=dining_category
        )

        posted_tx.refresh_from_db()
        check.equal(posted_tx.category, pre_set, "transaction keeps category")
        check.is_none(
            posted_tx.allocations.get().category, "allocation not backfilled"
        )

    ################################################################
    #
    @pytest.mark.parametrize(
        "raw_mcc,expected_code,expect_warning",
        [
            # Registry-known code: stored, no warning.
            ("5411", "5411", False),
            # Well-formed but registry-unknown: stored WITH warning --
            # the provider is authoritative, iso18245 lags.
            ("9999", "9999", True),
            ("0000", "0000", True),
            # Malformed: not stored, warning; raw survives in details.
            ("12AB", None, True),
            # Absent/empty: nothing stored, no warning.
            (None, None, False),
            ("", None, False),
        ],
    )
    def test_mcc_policy(
        self,
        posted_tx: Transaction,
        bofa_details: Callable[..., dict[str, Any]],
        raw_mcc: str | None,
        expected_code: str | None,
        expect_warning: bool,
    ) -> None:
        """
        GIVEN: a details dict with a given merchant_category_code
        WHEN:  details are applied
        THEN:  the MCC storage policy (store any 4 digits, warn-only
               validation) is honored and never fails the request
        """
        raw = bofa_details(merchant_category_code=raw_mcc)
        status, warnings = details_svc.apply_details(posted_tx, raw)

        check.equal(status, details_svc.STATUS_APPLIED, "applied")
        check.equal(bool(warnings), expect_warning, "warning as expected")
        posted_tx.refresh_from_db()
        check.equal(
            posted_tx.merchant_category_code, expected_code, "stored code"
        )
        assert posted_tx.details is not None
        check.equal(
            posted_tx.details["merchant_category_code"],
            raw_mcc,
            "raw value always survives in the details JSON",
        )

    ################################################################
    #
    def test_intermediary_purchase_sets_token_and_composes_via_platform(
        self,
        account: BankAccount,
        transaction_factory: Callable[..., Transaction],
        bofa_details: Callable[..., dict[str, Any]],
        merchant_place: MerchantPlace,
    ) -> None:
        """
        GIVEN: a transaction routed through a known payment platform
               (Toast), unresolved by the provider's own merchant_name
        WHEN:  details are applied
        THEN:  the real store is recovered into merchant_name,
               merchant_intermediary records the platform token, and
               the composed description appends "via <Platform>"
        """
        tx = transaction_factory(
            bank_account=account,
            pending=False,
            posted_date=datetime(2026, 7, 10, tzinfo=UTC),
            raw_description=(
                "TST*ACME BISTRO 07/09 MOBILE PURCHASE "
                f"{merchant_place.city} {merchant_place.region}"
            ),
        )
        raw = bofa_details(
            merchant_name="TST*ACME BISTRO",
            merchant_information=(
                f"{merchant_place.city}, {merchant_place.region}"
            ),
            merchant_category="Eating Places and Restaurants",
        )

        status, warnings = details_svc.apply_details(tx, raw)

        check.equal(status, details_svc.STATUS_APPLIED, "applied")
        check.equal(warnings, [], "without warnings")
        tx.refresh_from_db()
        check.equal(tx.merchant_name, "ACME BISTRO", "real store recovered")
        check.equal(tx.merchant_intermediary, "toast", "platform recorded")
        check.equal(
            tx.description,
            f"ACME BISTRO -- {merchant_place.city}, {merchant_place.region} "
            "(Eating Places and Restaurants, via Toast)",
            "description names the platform",
        )

    ################################################################
    #
    def test_direct_purchase_leaves_intermediary_null(
        self,
        posted_tx: Transaction,
        bofa_details: Callable[..., dict[str, Any]],
    ) -> None:
        """
        GIVEN: a transaction with no known platform prefix
        WHEN:  details are applied
        THEN:  merchant_intermediary stays NULL and the description has
               no "via" clause
        """
        status, _ = details_svc.apply_details(posted_tx, bofa_details())

        assert status == details_svc.STATUS_APPLIED
        posted_tx.refresh_from_db()
        check.is_none(posted_tx.merchant_intermediary, "no intermediary")
        check.is_not_in("via", posted_tx.description, "no 'via' clause")

    ################################################################
    #
    def test_oversized_values_truncate_with_warning(
        self,
        posted_tx: Transaction,
        bofa_details: Callable[..., dict[str, Any]],
    ) -> None:
        """
        GIVEN: a details dict with an oversized merchant_name
        WHEN:  details are applied
        THEN:  the value is truncated to the column width with a
               warning instead of failing
        """
        status, warnings = details_svc.apply_details(
            posted_tx, bofa_details(merchant_name="M" * 200)
        )

        assert status == details_svc.STATUS_APPLIED
        check.is_true(
            any("merchant_name truncated" in w for w in warnings), "warned"
        )
        posted_tx.refresh_from_db()
        check.equal(posted_tx.merchant_name, "M" * 128, "truncated to width")


########################################################################
########################################################################
#
class TestTransactionDetailsEndpoint:
    """Tests for POST /api/v1/bank-accounts/{id}/transaction-details/."""

    ################################################################
    #
    def test_apply_mixed_batch(
        self,
        auth_client: APIClient,
        account: BankAccount,
        posted_tx: Transaction,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
        user_factory: Callable[..., User],
        dining_category: TransactionCategory,
        bofa_details: Callable[..., dict[str, Any]],
    ) -> None:
        """
        GIVEN: a batch with an unenriched posted row, a pending row, an
               already-enriched row, and a real transaction on someone
               else's account
        WHEN:  POSTed to the transaction-details action
        THEN:  every per-item status and summary count is exercised in
               one submission, and the foreign row is untouched
        """
        pending = transaction_factory(bank_account=account, pending=True)
        enriched = transaction_factory(bank_account=account, pending=False)
        details_svc.apply_details(enriched, bofa_details())
        other_tx = transaction_factory(
            bank_account=bank_account_factory(owners=[user_factory()]),
            pending=False,
        )

        response = auth_client.post(
            f"/api/v1/bank-accounts/{account.id}/transaction-details/",
            {
                "details": [
                    {
                        "transaction": str(posted_tx.id),
                        "details": bofa_details(),
                        "category": "Dining : Restaurants",
                    },
                    {
                        "transaction": str(pending.id),
                        "details": bofa_details(),
                    },
                    {
                        "transaction": str(enriched.id),
                        "details": bofa_details(),
                    },
                    # A real row on another user's account answers
                    # exactly like an unknown id -- no information
                    # leak about foreign transactions.
                    {
                        "transaction": str(other_tx.id),
                        "details": bofa_details(),
                    },
                ]
            },
            format="json",
        )

        assert response.status_code == 200
        data = response.json()
        check.equal(
            {
                k: data[k]
                for k in (
                    "applied",
                    "skipped_pending",
                    "skipped_has_details",
                    "not_found",
                )
            },
            {
                "applied": 1,
                "skipped_pending": 1,
                "skipped_has_details": 1,
                "not_found": 1,
            },
            "summary counts",
        )
        check.equal(
            [r["status"] for r in data["results"]],
            ["applied", "skipped_pending", "skipped_has_details", "not_found"],
            "per-item statuses",
        )
        posted_tx.refresh_from_db()
        check.equal(posted_tx.merchant_name, "Trader Joes", "row enriched")
        check.equal(posted_tx.category, dining_category, "category seeded")
        other_tx.refresh_from_db()
        check.is_none(other_tx.details, "foreign row untouched")

    ################################################################
    #
    def test_non_owner_gets_404(
        self,
        account: BankAccount,
        user_factory: Callable[..., User],
        make_auth_client: Callable[[User], APIClient],
    ) -> None:
        """
        GIVEN: an authenticated user who does not own the account
        WHEN:  they POST to its transaction-details action
        THEN:  the account is not found for them
        """
        response = make_auth_client(user_factory()).post(
            f"/api/v1/bank-accounts/{account.id}/transaction-details/",
            {"details": []},
            format="json",
        )
        assert response.status_code == 404

    ################################################################
    #
    def test_overwrite_flag_reapplies(
        self,
        auth_client: APIClient,
        account: BankAccount,
        posted_tx: Transaction,
        bofa_details: Callable[..., dict[str, Any]],
    ) -> None:
        """
        GIVEN: an already-enriched transaction
        WHEN:  the batch is re-POSTed with overwrite=true
        THEN:  the row is re-applied instead of skipped
        """
        details_svc.apply_details(posted_tx, bofa_details())

        response = auth_client.post(
            f"/api/v1/bank-accounts/{account.id}/transaction-details/",
            {
                "overwrite": True,
                "details": [
                    {
                        "transaction": str(posted_tx.id),
                        "details": bofa_details(
                            merchant_name="Trader Joes #123"
                        ),
                    }
                ],
            },
            format="json",
        )

        assert response.status_code == 200
        check.equal(response.json()["applied"], 1, "re-applied")
        posted_tx.refresh_from_db()
        check.equal(
            posted_tx.merchant_name, "Trader Joes #123", "with new values"
        )

    ################################################################
    #
    def test_unknown_category_warns_and_leaves_unassigned(
        self,
        auth_client: APIClient,
        account: BankAccount,
        posted_tx: Transaction,
        bofa_details: Callable[..., dict[str, Any]],
    ) -> None:
        """
        GIVEN: an item naming a category the caller cannot see
        WHEN:  POSTed to the transaction-details action
        THEN:  the item still applies, a per-item warning reports the
               unknown name, the transaction stays unassigned, and no
               category is created
        """
        before = TransactionCategory.objects.count()

        response = auth_client.post(
            f"/api/v1/bank-accounts/{account.id}/transaction-details/",
            {
                "details": [
                    {
                        "transaction": str(posted_tx.id),
                        "details": bofa_details(),
                        "category": "No Such : Category",
                    }
                ]
            },
            format="json",
        )

        assert response.status_code == 200
        data = response.json()
        check.equal(data["applied"], 1, "item still applied")
        check.is_true(
            any(
                "unknown category" in w for w in data["results"][0]["warnings"]
            ),
            "warning names the unknown category",
        )
        posted_tx.refresh_from_db()
        check.is_none(posted_tx.category, "transaction stays unassigned")
        check.equal(
            TransactionCategory.objects.count(), before, "nothing created"
        )


########################################################################
########################################################################
#
class TestTransactionMerchantAPI:
    """Merchant fields on the transaction list/detail API."""

    ################################################################
    #
    @pytest.fixture
    def enriched_tx(
        self,
        posted_tx: Transaction,
        bofa_details: Callable[..., dict[str, Any]],
    ) -> Transaction:
        """posted_tx after a full enrichment pass."""
        details_svc.apply_details(posted_tx, bofa_details())
        posted_tx.refresh_from_db()
        return posted_tx

    ################################################################
    #
    @pytest.mark.parametrize(
        "query,expect_match",
        [
            ("merchant_name=trader", True),
            ("merchant_name=costco", False),
            ("merchant_city={city_word}", True),
            ("merchant_region={region}", True),
            ("merchant_region=zz", False),
            ("merchant_category_code=5411", True),
            ("merchant_category_code=5812", False),
            ("virtual_card_last4=1439", True),
            ("virtual_card_last4=9999", False),
            ("has_details=true", True),
            ("has_details=false", False),
        ],
    )
    def test_merchant_filters(
        self,
        auth_client: APIClient,
        enriched_tx: Transaction,
        merchant_place: MerchantPlace,
        query: str,
        expect_match: bool,
    ) -> None:
        """
        GIVEN: one enriched transaction
        WHEN:  the transaction list is filtered by a merchant lookup
               (the city by one word of its name, the region exactly)
        THEN:  the row matches (or not) as expected
        """
        query = query.format(
            city_word=merchant_place.city.split()[-1].lower(),
            region=merchant_place.region.lower(),
        )
        response = auth_client.get(f"/api/v1/transactions/?{query}")
        assert response.status_code == 200
        ids = [row["id"] for row in response.json()["results"]]
        assert (str(enriched_tx.id) in ids) is expect_match

    ################################################################
    #
    @pytest.mark.parametrize(
        "query,expect_match",
        [
            ("merchant_intermediary=toast", True),
            ("merchant_intermediary=TOAST", True),
            ("merchant_intermediary=grubhub", False),
        ],
    )
    def test_merchant_intermediary_filter(
        self,
        auth_client: APIClient,
        account: BankAccount,
        transaction_factory: Callable[..., Transaction],
        bofa_details: Callable[..., dict[str, Any]],
        merchant_place: MerchantPlace,
        query: str,
        expect_match: bool,
    ) -> None:
        """
        GIVEN: a transaction enriched through a known payment platform
        WHEN:  the transaction list is filtered by merchant_intermediary
        THEN:  the row matches case-insensitively by token
        """
        tx = transaction_factory(
            bank_account=account,
            pending=False,
            raw_description=(
                "TST*ACME BISTRO 07/09 MOBILE PURCHASE "
                f"{merchant_place.city} {merchant_place.region}"
            ),
        )
        details_svc.apply_details(
            tx, bofa_details(merchant_name="TST*ACME BISTRO")
        )

        response = auth_client.get(f"/api/v1/transactions/?{query}")
        assert response.status_code == 200
        ids = [row["id"] for row in response.json()["results"]]
        assert (str(tx.id) in ids) is expect_match

    ################################################################
    #
    def test_merchant_fields_serialized(
        self,
        auth_client: APIClient,
        enriched_tx: Transaction,
        merchant_place: MerchantPlace,
    ) -> None:
        """
        GIVEN: an enriched transaction
        WHEN:  it is retrieved through the API
        THEN:  the merchant columns and has_details are present and
               the raw details JSON is not exposed
        """
        response = auth_client.get(f"/api/v1/transactions/{enriched_tx.id}/")
        assert response.status_code == 200
        data = response.json()
        check.equal(
            {
                k: data[k]
                for k in (
                    "merchant_name",
                    "merchant_city",
                    "merchant_region",
                    "merchant_country",
                    "merchant_category_code",
                    "virtual_card_number",
                    "has_details",
                    "description_user_edited",
                )
            },
            {
                "merchant_name": "Trader Joes",
                "merchant_city": merchant_place.city.upper(),
                "merchant_region": merchant_place.region,
                "merchant_country": "US",
                "merchant_category_code": "5411",
                "virtual_card_number": "XXXX-XXXX-XXXX-1439",
                "has_details": True,
                "description_user_edited": False,
            },
            "merchant columns and flags serialized",
        )
        check.is_not_in("details", data, "raw details JSON not exposed")

    ################################################################
    #
    def test_location_fields_are_writable(
        self,
        auth_client: APIClient,
        enriched_tx: Transaction,
        merchant_place: MerchantPlace,
    ) -> None:
        """
        GIVEN: an enriched transaction
        WHEN:  the user PATCHes the location fields
        THEN:  they update (the scraper-owned columns do not)
        """
        response = auth_client.patch(
            f"/api/v1/transactions/{enriched_tx.id}/",
            {
                "merchant_address": merchant_place.street,
                "merchant_city": merchant_place.city,
                "merchant_latitude": merchant_place.latitude,
                "merchant_longitude": merchant_place.longitude,
                # Read-only: silently ignored.
                "merchant_name": "Hacked Name",
            },
            format="json",
        )

        assert response.status_code == 200
        enriched_tx.refresh_from_db()
        check.equal(
            (
                enriched_tx.merchant_address,
                enriched_tx.merchant_city,
                str(enriched_tx.merchant_latitude),
                str(enriched_tx.merchant_longitude),
            ),
            (
                merchant_place.street,
                merchant_place.city,
                merchant_place.latitude,
                merchant_place.longitude,
            ),
            "location fields updated",
        )
        check.equal(
            enriched_tx.merchant_name,
            "Trader Joes",
            "read-only merchant_name ignored",
        )

    ################################################################
    #
    def test_description_change_sets_user_edited_flag(
        self,
        auth_client: APIClient,
        posted_tx: Transaction,
        bofa_details: Callable[..., dict[str, Any]],
    ) -> None:
        """
        GIVEN: a transaction with an untouched description
        WHEN:  the user PATCHes a new description, then it is enriched
        THEN:  description_user_edited is set, and the enrichment leaves
               the user's description alone
        """
        response = auth_client.patch(
            f"/api/v1/transactions/{posted_tx.id}/",
            {"description": "My custom label"},
            format="json",
        )
        assert response.status_code == 200
        posted_tx.refresh_from_db()
        assert posted_tx.description_user_edited

        details_svc.apply_details(posted_tx, bofa_details())

        posted_tx.refresh_from_db()
        assert posted_tx.description == "My custom label"

    ################################################################
    #
    def test_unchanged_description_leaves_flag_off(
        self, auth_client: APIClient, posted_tx: Transaction
    ) -> None:
        """
        GIVEN: a transaction with an untouched description
        WHEN:  the user PATCHes the same description back
        THEN:  description_user_edited stays off
        """
        response = auth_client.patch(
            f"/api/v1/transactions/{posted_tx.id}/",
            {"description": posted_tx.description},
            format="json",
        )

        assert response.status_code == 200
        posted_tx.refresh_from_db()
        assert not posted_tx.description_user_edited
