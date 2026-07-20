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
from rest_framework.test import APIClient

# Project imports
#
from moneypools.description_utils import compose_enriched_description
from moneypools.models import BankAccount, Transaction, TransactionCategory
from moneypools.service import transaction_details as details_svc
from users.models import User

pytestmark = pytest.mark.django_db


########################################################################
####################################################################
#
@pytest.fixture
def bofa_details() -> Callable[..., dict[str, Any]]:
    """Factory building a details dict shaped like bofa_scraper output.

    Merchant/city values are made up; no real data.  Keyword arguments
    override (or add) keys.
    """

    def _build(**overrides: Any) -> dict[str, Any]:
        details: dict[str, Any] = {
            "merchant_name": "Trader Joes",
            "merchant_information": "MENLO PARK, CA",
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
def account(
    bank_account_factory: Callable[..., BankAccount],
    user: User,
) -> BankAccount:
    """A bank account owned by the default ``user`` fixture."""
    return bank_account_factory(owners=[user])


########################################################################
####################################################################
#
@pytest.fixture
def posted_tx(
    account: BankAccount,
    transaction_factory: Callable[..., Transaction],
) -> Transaction:
    """A posted, never-enriched transaction on ``account``."""
    return transaction_factory(
        bank_account=account,
        pending=False,
        posted_date=datetime(2026, 7, 10, tzinfo=UTC),
        raw_description="TRADER JOES 07/09 MOBILE PURCHASE MENLO PARK CA",
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
            # The BofA 'CITY, ST' form parses fully.
            ("MENLO PARK, CA", ("MENLO PARK", "CA", "US")),
            # Internal whitespace is collapsed before matching.
            ("  MENLO   PARK ,  CA  ", ("MENLO PARK", "CA", "US")),
            # Anything else lands verbatim in city with no
            # region/country -- a lowercase state code does not match
            # the 'CITY, ST' pattern.
            ("Springfield, il", ("Springfield, il", None, None)),
            ("TOKYO", ("TOKYO", None, None)),
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
                "Menlo Park",
                None,
                None,
                "Trader Joes -- Menlo Park",
            ),
            (None, "Menlo Park", "CA", None, "Menlo Park, CA"),
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

        assert status == details_svc.STATUS_APPLIED
        assert warnings == []

        posted_tx.refresh_from_db()
        assert posted_tx.details == raw
        assert posted_tx.merchant_name == "Trader Joes"
        assert posted_tx.merchant_city == "MENLO PARK"
        assert posted_tx.merchant_region == "CA"
        assert posted_tx.merchant_country == "US"
        assert posted_tx.merchant_category == (
            "Grocery Stores and Supermarkets"
        )
        assert posted_tx.merchant_category_code == "5411"
        assert posted_tx.virtual_card_number == "XXXX-XXXX-XXXX-1439"
        # phone_number lives only in the details JSON.
        assert posted_tx.details["phone_number"] == "800-555-0100"

        assert posted_tx.category == dining_category
        allocation = posted_tx.allocations.get()
        assert allocation.category == dining_category

        assert posted_tx.description == (
            "Trader Joes -- MENLO PARK, CA (Grocery Stores and Supermarkets)"
        )

    ################################################################
    #
    @pytest.mark.parametrize(
        "scenario,expected_status",
        [
            ("pending", details_svc.STATUS_SKIPPED_PENDING),
            ("already_enriched", details_svc.STATUS_SKIPPED_HAS_DETAILS),
        ],
    )
    def test_skip_statuses_leave_row_untouched(
        self,
        account: BankAccount,
        transaction_factory: Callable[..., Transaction],
        bofa_details: Callable[..., dict[str, Any]],
        scenario: str,
        expected_status: str,
    ) -> None:
        """
        GIVEN: a transaction that must not be (re-)enriched -- pending,
               or already enriched without overwrite
        WHEN:  details are applied
        THEN:  the expected skip status is returned and the row is
               unchanged
        """
        if scenario == "pending":
            tx = transaction_factory(bank_account=account, pending=True)
        else:
            tx = transaction_factory(bank_account=account, pending=False)
            details_svc.apply_details(tx, bofa_details())
            tx.refresh_from_db()
        baseline_name = tx.merchant_name

        status, warnings = details_svc.apply_details(
            tx, bofa_details(merchant_name="Imposter Mart")
        )

        assert status == expected_status
        assert warnings == []
        tx.refresh_from_db()
        assert tx.merchant_name == baseline_name

    ################################################################
    #
    def test_overwrite_replaces_scraper_owned_fields_only(
        self,
        posted_tx: Transaction,
        dining_category: TransactionCategory,
        transaction_category_factory: Callable[..., TransactionCategory],
        bofa_details: Callable[..., dict[str, Any]],
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
                merchant_information="PALO ALTO, CA",
            ),
            category=dining_category,
            overwrite=True,
        )

        assert status == details_svc.STATUS_APPLIED
        posted_tx.refresh_from_db()
        # Scraper-owned column updated.
        assert posted_tx.merchant_name == "Trader Joes #123"
        # Location was already set by the first enrichment -- never
        # clobbered, even by overwrite.
        assert posted_tx.merchant_city == "MENLO PARK"
        # User's category assignment survives.
        assert posted_tx.category == user_category
        # Description recomposes only on FIRST enrichment.
        assert posted_tx.description == original_description

    ################################################################
    #
    def test_user_location_wins_over_enrichment(
        self,
        posted_tx: Transaction,
        bofa_details: Callable[..., dict[str, Any]],
    ) -> None:
        """
        GIVEN: a transaction whose location was set by the user before
               enrichment ever ran
        WHEN:  details are applied
        THEN:  the user's location values are preserved and only the
               fields the user left empty are filled
        """
        posted_tx.merchant_city = "Redwood City"
        posted_tx.merchant_address = "1001 Example Ave"
        posted_tx.save()

        status, _ = details_svc.apply_details(posted_tx, bofa_details())

        assert status == details_svc.STATUS_APPLIED
        posted_tx.refresh_from_db()
        assert posted_tx.merchant_city == "Redwood City"
        assert posted_tx.merchant_address == "1001 Example Ave"
        assert posted_tx.merchant_region == "CA"
        assert posted_tx.merchant_country == "US"

    ################################################################
    #
    @pytest.mark.parametrize("preset_on", ["allocation", "transaction"])
    def test_category_seeding_guards(
        self,
        account: BankAccount,
        transaction_factory: Callable[..., Transaction],
        transaction_category_factory: Callable[..., TransactionCategory],
        dining_category: TransactionCategory,
        bofa_details: Callable[..., dict[str, Any]],
        preset_on: str,
    ) -> None:
        """
        GIVEN: a transaction already categorized on one level -- its
               allocation, or the transaction itself
        WHEN:  details are applied with a different category
        THEN:  seeding fills only the NULL slots; an assigned category
               is never overwritten and never triggers a backfill
        """
        tx = transaction_factory(bank_account=account, pending=False)
        pre_set = transaction_category_factory(group="Home", name="Rent")
        allocation = tx.allocations.get()
        if preset_on == "allocation":
            allocation.category = pre_set
            allocation.save()
        else:
            tx.category = pre_set
            tx.save()

        details_svc.apply_details(tx, bofa_details(), category=dining_category)

        tx.refresh_from_db()
        allocation.refresh_from_db()
        if preset_on == "allocation":
            # The transaction's NULL slot seeds; the pre-categorized
            # allocation is left alone.
            assert tx.category == dining_category
            assert allocation.category == pre_set
        else:
            # An assigned transaction never re-seeds, and seeding not
            # firing means its allocation is not backfilled either.
            assert tx.category == pre_set
            assert allocation.category is None

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
            ("123", None, True),
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

        assert status == details_svc.STATUS_APPLIED
        assert bool(warnings) is expect_warning
        posted_tx.refresh_from_db()
        assert posted_tx.merchant_category_code == expected_code
        # The raw value always survives in the stored details JSON.
        assert posted_tx.details is not None
        assert posted_tx.details["merchant_category_code"] == raw_mcc

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
        assert any("merchant_name truncated" in w for w in warnings)
        posted_tx.refresh_from_db()
        assert posted_tx.merchant_name == "M" * 128


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
        assert data["applied"] == 1
        assert data["skipped_pending"] == 1
        assert data["skipped_has_details"] == 1
        assert data["not_found"] == 1
        statuses = [r["status"] for r in data["results"]]
        assert statuses == [
            "applied",
            "skipped_pending",
            "skipped_has_details",
            "not_found",
        ]

        posted_tx.refresh_from_db()
        assert posted_tx.merchant_name == "Trader Joes"
        assert posted_tx.category == dining_category
        other_tx.refresh_from_db()
        assert other_tx.details is None

    ################################################################
    #
    def test_non_owner_gets_404(
        self,
        api_client: APIClient,
        account: BankAccount,
        user_factory: Callable[..., User],
    ) -> None:
        """
        GIVEN: an authenticated user who does not own the account
        WHEN:  they POST to its transaction-details action
        THEN:  the account is not found for them
        """
        api_client.force_authenticate(user=user_factory())
        response = api_client.post(
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
        assert response.json()["applied"] == 1
        posted_tx.refresh_from_db()
        assert posted_tx.merchant_name == "Trader Joes #123"

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
        assert data["applied"] == 1
        warnings = data["results"][0]["warnings"]
        assert any("unknown category" in w for w in warnings)
        posted_tx.refresh_from_db()
        assert posted_tx.category is None
        assert TransactionCategory.objects.count() == before


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
            ("merchant_city=menlo", True),
            ("merchant_region=ca", True),
            ("merchant_region=il", False),
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
        query: str,
        expect_match: bool,
    ) -> None:
        """
        GIVEN: one enriched transaction
        WHEN:  the transaction list is filtered by a merchant lookup
        THEN:  the row matches (or not) as expected
        """
        response = auth_client.get(f"/api/v1/transactions/?{query}")
        assert response.status_code == 200
        ids = [row["id"] for row in response.json()["results"]]
        assert (str(enriched_tx.id) in ids) is expect_match

    ################################################################
    #
    def test_merchant_fields_serialized(
        self, auth_client: APIClient, enriched_tx: Transaction
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
        assert data["merchant_name"] == "Trader Joes"
        assert data["merchant_city"] == "MENLO PARK"
        assert data["merchant_region"] == "CA"
        assert data["merchant_country"] == "US"
        assert data["merchant_category_code"] == "5411"
        assert data["virtual_card_number"] == "XXXX-XXXX-XXXX-1439"
        assert data["has_details"] is True
        assert data["description_user_edited"] is False
        assert "details" not in data

    ################################################################
    #
    def test_location_fields_are_writable(
        self, auth_client: APIClient, enriched_tx: Transaction
    ) -> None:
        """
        GIVEN: an enriched transaction
        WHEN:  the user PATCHes the location fields
        THEN:  they update (the scraper-owned columns do not)
        """
        response = auth_client.patch(
            f"/api/v1/transactions/{enriched_tx.id}/",
            {
                "merchant_address": "700 Example St",
                "merchant_city": "Menlo Park",
                "merchant_latitude": "37.453000",
                "merchant_longitude": "-122.182000",
                # Read-only: silently ignored.
                "merchant_name": "Hacked Name",
            },
            format="json",
        )

        assert response.status_code == 200
        enriched_tx.refresh_from_db()
        assert enriched_tx.merchant_address == "700 Example St"
        assert enriched_tx.merchant_city == "Menlo Park"
        assert str(enriched_tx.merchant_latitude) == "37.453000"
        assert str(enriched_tx.merchant_longitude) == "-122.182000"
        assert enriched_tx.merchant_name == "Trader Joes"

    ################################################################
    #
    @pytest.mark.parametrize("same_value", [False, True])
    def test_description_patch_sets_user_edited_flag(
        self,
        auth_client: APIClient,
        posted_tx: Transaction,
        bofa_details: Callable[..., dict[str, Any]],
        same_value: bool,
    ) -> None:
        """
        GIVEN: a transaction with an untouched description
        WHEN:  the user PATCHes a description (changed or identical)
        THEN:  description_user_edited flips on only for a real
               change, and a later enrichment then leaves the user's
               description alone
        """
        new_description = (
            posted_tx.description if same_value else "My custom label"
        )
        response = auth_client.patch(
            f"/api/v1/transactions/{posted_tx.id}/",
            {"description": new_description},
            format="json",
        )

        assert response.status_code == 200
        posted_tx.refresh_from_db()
        assert posted_tx.description_user_edited is not same_value

        if not same_value:
            details_svc.apply_details(posted_tx, bofa_details())
            posted_tx.refresh_from_db()
            assert posted_tx.description == "My custom label"
