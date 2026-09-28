#!/usr/bin/env python
#
"""Tests for TransactionCategory: model, resolution, visibility, and API."""

# system imports
from collections.abc import Callable
from typing import Any

# 3rd party imports
import pytest
import pytest_check as check
from django.db import IntegrityError
from django.db import transaction as db_transaction
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

# Project imports
from importers.bofa_categories import BOFA_CATEGORY_MAP
from moneypools.management.commands.import_bank_account import (
    _resolve_category,
)
from moneypools.models import (
    BankAccount,
    Budget,
    Transaction,
    TransactionCategory,
)
from moneypools.service import categories as categories_svc
from moneypools.service import (
    transaction_allocation as transaction_allocation_svc,
)
from users.models import User

pytestmark = pytest.mark.django_db


####################################################################
#
@pytest.fixture
def groceries() -> TransactionCategory:
    """The seeded global 'Food & Drink : Groceries' category."""
    return TransactionCategory.objects.get(
        owner__isnull=True, group="Food & Drink", name="Groceries"
    )


########################################################################
########################################################################
#
class TestNormalization:
    """Tests for category-string normalization."""

    ################################################################
    #
    @pytest.mark.parametrize(
        "raw,expected",
        [
            # Both sides stripped, internal whitespace collapsed.
            (
                "  Education:  Tuition   & Fees ",
                ("Education", "Tuition & Fees"),
            ),
            # No colon -> single-level, group == name.
            ("Travel", ("Travel", "Travel")),
            # Only the FIRST colon splits; later colons stay in the name.
            ("Taxes: State: CA", ("Taxes", "State: CA")),
            # Trailing colon -> empty name falls back to the group.
            ("Misc:", ("Misc", "Misc")),
        ],
    )
    def test_normalize_category(
        self, raw: str, expected: tuple[str, str]
    ) -> None:
        """
        GIVEN: a raw provider category string
        WHEN:  it is normalized
        THEN:  it splits on the first colon, strips, and collapses whitespace
        """
        assert categories_svc.normalize_category(raw) == expected


########################################################################
########################################################################
#
class TestUniquenessConstraints:
    """Tests for the case-insensitive uniqueness constraints."""

    ################################################################
    #
    def test_global_uniqueness_case_insensitive(self) -> None:
        """
        GIVEN: a global category
        WHEN:  another global category with the same case-folded name is added
        THEN:  the unique constraint rejects it
        """
        TransactionCategory.objects.create(group="Zeta", name="Alpha")
        with pytest.raises(IntegrityError):
            with db_transaction.atomic():
                TransactionCategory.objects.create(group="zeta", name="alpha")

    ################################################################
    #
    def test_per_owner_uniqueness_independent_of_global(
        self, user: User, user_factory: Callable[..., User]
    ) -> None:
        """
        GIVEN: a global category named (G, N)
        WHEN:  two different users each create their own (G, N)
        THEN:  both succeed, but a second row for one owner is rejected
        """
        TransactionCategory.objects.create(group="Hobbies", name="Kites")
        c1 = TransactionCategory.objects.create(
            group="Hobbies", name="Kites", owner=user
        )
        c2 = TransactionCategory.objects.create(
            group="Hobbies", name="Kites", owner=user_factory()
        )
        assert c1.pkid != c2.pkid

        with pytest.raises(IntegrityError):
            with db_transaction.atomic():
                TransactionCategory.objects.create(
                    group="hobbies", name="kites", owner=user
                )


########################################################################
########################################################################
#
class TestVisibility:
    """Tests for TransactionCategoryQuerySet.visible_to.

    Global-vs-own-vs-stranger visibility is covered end-to-end by
    TestCategoryAPI.test_list_scopes; these cover the two harder paths
    that are awkward to exercise through the API.
    """

    ################################################################
    #
    def test_shared_account_makes_owner_categories_visible(
        self,
        user: User,
        user_factory: Callable[..., User],
        bank_account_factory: Callable[..., BankAccount],
        transaction_category_factory: Callable[..., TransactionCategory],
    ) -> None:
        """
        GIVEN: two users co-owning a bank account
        WHEN:  one creates a custom category
        THEN:  the co-owner can see it
        """
        other = user_factory()
        bank_account_factory(owners=[user, other])
        theirs = transaction_category_factory(owner=other)

        assert (
            TransactionCategory.objects.visible_to(user)
            .filter(pk=theirs.pk)
            .exists()
        )

    ################################################################
    #
    def test_grandfathered_after_unshare(
        self,
        user: User,
        user_factory: Callable[..., User],
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
        transaction_category_factory: Callable[..., TransactionCategory],
    ) -> None:
        """
        GIVEN: a co-owner's category referenced by a transaction on the
               shared account, then the co-owner is removed
        WHEN:  visibility is recomputed
        THEN:  the referenced category stays visible (grandfathered)
        """
        other = user_factory()
        account = bank_account_factory(owners=[user, other])
        category = transaction_category_factory(owner=other)
        transaction_factory(bank_account=account, category=category)

        account.owners.remove(other)

        assert (
            TransactionCategory.objects.visible_to(user)
            .filter(pk=category.pk)
            .exists()
        )


########################################################################
########################################################################
#
class TestAllocationCopiesCategory:
    """The allocation copies the transaction's category at creation."""

    ################################################################
    #
    @pytest.fixture
    def categorized_tx(
        self,
        transaction_factory: Callable[..., Transaction],
        transaction_category_factory: Callable[..., TransactionCategory],
    ) -> Transaction:
        """A transaction with a category of its own."""
        return transaction_factory(category=transaction_category_factory())

    ################################################################
    #
    @pytest.fixture
    def budget(
        self,
        categorized_tx: Transaction,
        budget_factory: Callable[..., Budget],
    ) -> Budget:
        """A budget on the same account as `categorized_tx`."""
        return budget_factory(bank_account=categorized_tx.bank_account)

    ################################################################
    #
    def test_transaction_category_copied(
        self, categorized_tx: Transaction, budget: Budget
    ) -> None:
        """
        GIVEN: a transaction with a category
        WHEN:  an allocation is created without a category
        THEN:  the transaction's category is copied onto it
        """
        allocation = transaction_allocation_svc.create(
            transaction=categorized_tx,
            budget=budget,
            amount=categorized_tx.amount,
        )

        # The category FK uses to_field="id", so category_id is the UUID.
        assert categorized_tx.category is not None
        assert allocation.category_id == categorized_tx.category.id

    ################################################################
    #
    def test_explicit_category_wins(
        self,
        categorized_tx: Transaction,
        budget: Budget,
        transaction_category_factory: Callable[..., TransactionCategory],
    ) -> None:
        """
        GIVEN: a transaction with a category
        WHEN:  an allocation is created with a different explicit category
        THEN:  the explicit category is used
        """
        explicit = transaction_category_factory()

        allocation = transaction_allocation_svc.create(
            transaction=categorized_tx,
            budget=budget,
            amount=categorized_tx.amount,
            category=explicit,
        )

        assert allocation.category_id == explicit.id


########################################################################
########################################################################
#
class TestResolveCategoryString:
    """Tests for export/import category-string resolution.

    Matching relies on the global rows seeded by migration 0038.
    """

    ################################################################
    #
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Food & Drink:Groceries", ("Food & Drink", "Groceries")),
            # Legacy enum-era spellings map onto the renamed rows.
            ("Food & Drink:Alcohol & Bars", ("Food & Drink", "Alcohol")),
            (
                "Transportation:Taxies",
                ("Transportation", "Taxis & Rideshare"),
            ),
        ],
    )
    def test_matches_seeded_row(
        self, raw: str, expected: tuple[str, str]
    ) -> None:
        """
        GIVEN: a category string from an export file
        WHEN:  it is resolved
        THEN:  it maps onto the existing seeded global row (including
               enum-era spellings of renamed rows)
        """
        category = categories_svc.resolve_category_string(raw)

        assert category is not None
        check.equal((category.group, category.name), expected, "the row")
        check.is_none(category.owner_id, "a global row")

    ################################################################
    #
    def test_auto_create_for_unknown(self) -> None:
        """
        GIVEN: a raw string matching nothing
        WHEN:  it is resolved
        THEN:  a new global row is created (an import never drops data)
        """
        before = TransactionCategory.objects.count()

        category = categories_svc.resolve_category_string("Nonsense : Widget")

        assert category is not None
        check.equal(
            (category.group, category.name), ("Nonsense", "Widget"), "the row"
        )
        check.is_none(category.owner_id, "a global row")
        check.equal(
            TransactionCategory.objects.count(), before + 1, "newly created"
        )

    ################################################################
    #
    def test_blank_resolves_to_none(self) -> None:
        """
        GIVEN: a blank raw string
        WHEN:  it is resolved
        THEN:  None (unassigned) is returned
        """
        assert categories_svc.resolve_category_string("   ") is None


########################################################################
########################################################################
#
class TestFindCategoryForUser:
    """Tests for resolving API-supplied category full names.

    This is the lookup behind the transaction-details `category` field:
    importers submit mibudge full names, matched among the categories
    visible to the caller, never creating anything.
    """

    ################################################################
    #
    def test_global_match_is_case_insensitive(
        self, user: User, groceries: TransactionCategory
    ) -> None:
        """
        GIVEN: a canonical full name in non-canonical case
        WHEN:  it is resolved for a user
        THEN:  the seeded global row is returned
        """
        found = categories_svc.find_category_for_user(
            user, "food & drink : GROCERIES"
        )
        assert found == groceries

    ################################################################
    #
    def test_custom_category_resolves_for_owner(
        self,
        user: User,
        transaction_category_factory: Callable[..., TransactionCategory],
    ) -> None:
        """
        GIVEN: a user-owned custom category
        WHEN:  its full name is resolved for that user
        THEN:  the custom row is returned
        """
        custom = transaction_category_factory(owner=user)

        found = categories_svc.find_category_for_user(user, custom.full_name)

        assert found == custom

    ################################################################
    #
    def test_global_preferred_over_custom_duplicate(
        self,
        user: User,
        groceries: TransactionCategory,
        transaction_category_factory: Callable[..., TransactionCategory],
    ) -> None:
        """
        GIVEN: a custom category shadowing a global (group, name) pair
        WHEN:  the full name is resolved
        THEN:  the global row wins (canonical names mean the shared row)
        """
        transaction_category_factory(
            group=groceries.group, name=groceries.name, owner=user
        )

        found = categories_svc.find_category_for_user(user, groceries.full_name)

        assert found == groceries

    ################################################################
    #
    @pytest.mark.parametrize(
        "full_name",
        [
            pytest.param("No Such : Row", id="unknown"),
            pytest.param("Private : Thing", id="another-users-custom"),
        ],
    )
    def test_unmatched_returns_none_and_creates_nothing(
        self,
        user: User,
        user_factory: Callable[..., User],
        transaction_category_factory: Callable[..., TransactionCategory],
        full_name: str,
    ) -> None:
        """
        GIVEN: another user's unshared custom 'Private : Thing' category
        WHEN:  a name matching nothing, or that category's name, is
               resolved for the user
        THEN:  None is returned -- and nothing is ever created
        """
        transaction_category_factory(
            group="Private", name="Thing", owner=user_factory()
        )
        before = TransactionCategory.objects.count()

        found = categories_svc.find_category_for_user(user, full_name)

        check.is_none(found, "no match")
        check.equal(
            TransactionCategory.objects.count(), before, "nothing created"
        )


########################################################################
########################################################################
#
class TestCategoryAPI:
    """Tests for the transaction-categories REST endpoint."""

    ################################################################
    #
    def test_list_scopes(
        self,
        auth_client: APIClient,
        user: User,
        user_factory: Callable[..., User],
        transaction_category_factory: Callable[..., TransactionCategory],
    ) -> None:
        """
        GIVEN: an own category and an unrelated user's category
        WHEN:  the user lists with scope=mine
        THEN:  own appears; the stranger's does not
        """
        mine = transaction_category_factory(owner=user)
        stranger = transaction_category_factory(owner=user_factory())

        response = auth_client.get(
            reverse("api_v1:transaction-category-list"), {"scope": "mine"}
        )

        assert response.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in response.data["results"]}
        check.is_in(str(mine.id), ids, "own category listed")
        check.is_not_in(str(stranger.id), ids, "stranger's is not")

    ################################################################
    #
    def test_create_forces_owner_and_normalizes(
        self, auth_client: APIClient, user: User
    ) -> None:
        """
        GIVEN: an authenticated user
        WHEN:  they create a category with padded whitespace
        THEN:  it is owned by them and whitespace-normalized
        """
        response = auth_client.post(
            reverse("api_v1:transaction-category-list"),
            {"group": "  Custom  Group ", "name": "  My  Cat "},
        )

        assert response.status_code == status.HTTP_201_CREATED
        category = TransactionCategory.objects.get(id=response.data["id"])
        check.equal(category.owner_id, user.pk, "owned by the user")
        check.equal(
            (category.group, category.name),
            ("Custom Group", "My Cat"),
            "whitespace normalized",
        )

    ################################################################
    #
    def test_create_rejects_duplicate_of_global(
        self, auth_client: APIClient, groceries: TransactionCategory
    ) -> None:
        """
        GIVEN: a seeded global category
        WHEN:  the user creates a case-insensitive duplicate of it
        THEN:  it is rejected
        """
        response = auth_client.post(
            reverse("api_v1:transaction-category-list"),
            {"group": groceries.group.lower(), "name": groceries.name.lower()},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    ################################################################
    #
    def test_create_rejects_duplicate_of_own(
        self,
        auth_client: APIClient,
        user: User,
        transaction_category_factory: Callable[..., TransactionCategory],
    ) -> None:
        """
        GIVEN: a category the user owns
        WHEN:  the user creates a case-insensitive duplicate of it
        THEN:  it is rejected
        """
        own = transaction_category_factory(owner=user)

        response = auth_client.post(
            reverse("api_v1:transaction-category-list"),
            {"group": own.group.upper(), "name": own.name.upper()},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    ################################################################
    #
    @pytest.mark.parametrize("method", ["patch", "delete"])
    def test_global_rows_immutable_via_api(
        self,
        auth_client: APIClient,
        groceries: TransactionCategory,
        method: str,
    ) -> None:
        """
        GIVEN: a global category
        WHEN:  a user tries to modify or delete it
        THEN:  it is forbidden (global rows are admin-managed)
        """
        url = reverse(
            "api_v1:transaction-category-detail", kwargs={"id": groceries.id}
        )

        response = getattr(auth_client, method)(
            url, {"name": "Renamed"} if method == "patch" else None
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    ################################################################
    #
    def test_owner_delete_blocked_when_referenced(
        self,
        auth_client: APIClient,
        account: BankAccount,
        user: User,
        transaction_factory: Callable[..., Transaction],
        transaction_category_factory: Callable[..., TransactionCategory],
    ) -> None:
        """
        GIVEN: an owned category referenced by a transaction
        WHEN:  the owner deletes it
        THEN:  409 Conflict; the category remains
        """
        category = transaction_category_factory(owner=user)
        transaction_factory(bank_account=account, category=category)

        response = auth_client.delete(
            reverse(
                "api_v1:transaction-category-detail", kwargs={"id": category.id}
            )
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        assert TransactionCategory.objects.filter(pk=category.pkid).exists()

    ################################################################
    #
    def test_owner_delete_unreferenced(
        self,
        auth_client: APIClient,
        user: User,
        transaction_category_factory: Callable[..., TransactionCategory],
    ) -> None:
        """
        GIVEN: an owned category nothing references
        WHEN:  the owner deletes it
        THEN:  204 No Content; the category is gone
        """
        category = transaction_category_factory(owner=user)

        response = auth_client.delete(
            reverse(
                "api_v1:transaction-category-detail", kwargs={"id": category.id}
            )
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not TransactionCategory.objects.filter(pk=category.pkid).exists()

    ################################################################
    #
    def test_archive_action(
        self,
        auth_client: APIClient,
        user: User,
        transaction_category_factory: Callable[..., TransactionCategory],
    ) -> None:
        """
        GIVEN: an owned category
        WHEN:  the owner archives it
        THEN:  it is marked archived
        """
        category = transaction_category_factory(owner=user)

        response = auth_client.post(
            reverse(
                "api_v1:transaction-category-archive",
                kwargs={"id": category.id},
            )
        )

        assert response.status_code == status.HTTP_200_OK
        category.refresh_from_db()
        assert category.archived is True


########################################################################
########################################################################
#
class TestTransactionCategoryFilters:
    """Tests for category filters on the transaction endpoints."""

    ################################################################
    #
    @pytest.mark.parametrize(
        "filter_name,matches_categorized",
        [
            ("category", True),
            ("category_group", True),
            ("uncategorized", False),
        ],
    )
    def test_category_filters(
        self,
        auth_client: APIClient,
        account: BankAccount,
        groceries: TransactionCategory,
        transaction_factory: Callable[..., Transaction],
        filter_name: str,
        matches_categorized: bool,
    ) -> None:
        """
        GIVEN: one transaction categorized as Groceries and one
               uncategorized
        WHEN:  the transaction list is filtered by category id, by
               (case-insensitive) category group, or uncategorized
        THEN:  exactly the matching transaction is returned
        """
        categorized = transaction_factory(
            bank_account=account, category=groceries
        )
        uncategorized = transaction_factory(bank_account=account)
        params = {
            "category": {"category": str(groceries.id)},
            "category_group": {"category_group": "food & drink"},
            "uncategorized": {"uncategorized": "true"},
        }[filter_name]
        expected = categorized if matches_categorized else uncategorized

        response = auth_client.get(reverse("api_v1:transaction-list"), params)

        assert response.status_code == status.HTTP_200_OK
        assert [row["id"] for row in response.data["results"]] == [
            str(expected.id)
        ]


########################################################################
########################################################################
#
class TestAutoSpendValidation:
    """Tests for Budget.auto_spend serializer validation."""

    ################################################################
    #
    @pytest.fixture
    def post_budget(
        self, auth_client: APIClient, account: BankAccount
    ) -> Callable[[list[str]], Any]:
        """Return a function POSTing a budget with the given auto_spend."""

        def _post(auto_spend: list[str]) -> Any:
            return auth_client.post(
                reverse("api_v1:budget-list"),
                {
                    "name": "Budget",
                    "bank_account": str(account.id),
                    "budget_type": Budget.BudgetType.GOAL,
                    "funding_type": Budget.FundingType.FIXED_AMOUNT,
                    "target_balance": "100.00",
                    "funding_amount": "10.00",
                    "auto_spend": auto_spend,
                },
                format="json",
            )

        return _post

    ################################################################
    #
    def test_visible_category_accepted_as_canonical_name(
        self, post_budget: Callable[[list[str]], Any]
    ) -> None:
        """
        GIVEN: an auto_spend entry naming a visible category in
               non-canonical form
        WHEN:  a budget is created
        THEN:  it is accepted and rewritten to the canonical full name
        """
        response = post_budget(["food & drink:groceries"])

        assert response.status_code == status.HTTP_201_CREATED, response.data
        budget = Budget.objects.get(id=response.data["id"])
        assert budget.auto_spend == ["Food & Drink : Groceries"]

    ################################################################
    #
    def test_unknown_category_rejected(
        self, post_budget: Callable[[list[str]], Any]
    ) -> None:
        """
        GIVEN: an auto_spend entry naming no visible category
        WHEN:  a budget is created
        THEN:  it is rejected
        """
        response = post_budget(["No Such : Category"])

        assert response.status_code == status.HTTP_400_BAD_REQUEST


########################################################################
########################################################################
#
class TestImportCategoryResolution:
    """Tests for _resolve_category in the import_bank_account command.

    This is the same normalization/mapping the data migration applies to
    stored allocation categories, exercised through the supported path:
    the legacy sentinel becomes NULL, a stored typo maps onto the fixed
    seeded row, and current full names resolve directly.
    """

    ################################################################
    #
    @pytest.mark.parametrize(
        "raw",
        [
            pytest.param(None, id="blank"),
            pytest.param("Uncategorized:Unassigned", id="legacy-sentinel"),
        ],
    )
    def test_blank_and_sentinel_resolve_to_none(self, raw: str | None) -> None:
        """
        GIVEN: a blank value or the legacy unassigned sentinel
        WHEN:  it is resolved during import
        THEN:  it maps to None (unassigned)
        """
        assert _resolve_category(raw) is None

    ################################################################
    #
    def test_legacy_typo_maps_to_fixed_row(self) -> None:
        """
        GIVEN: the legacy 'Education: Tuition & Fees' typo string
        WHEN:  it is resolved during import
        THEN:  it maps onto the fixed seeded 'Education : Tuition & Fees' row
        """
        category = _resolve_category("Education: Tuition & Fees")

        assert category is not None
        check.equal(
            (category.group, category.name),
            ("Education", "Tuition & Fees"),
            "the fixed row",
        )
        check.is_none(category.owner_id, "a global row")


########################################################################
########################################################################
#
class TestImporterMapTargets:
    """The BofA importer's map must target real canonical categories.

    Checked against the seeded global rows in the migrated test
    database (not the migration source), so it survives migration
    squashes.  A stray target is a typo in the importer map or a
    canonical-list change the map has not caught up with -- either
    way, that category would silently land unassigned on every
    future import.
    """

    ################################################################
    #
    def test_targets_exist_in_seeded_globals(self) -> None:
        """
        GIVEN: the BofA importer's built-in category map
        WHEN:  its non-null targets are checked against the seeded
               global categories
        THEN:  every target matches a canonical full name
        """
        canonical = {
            category.full_name.casefold()
            for category in TransactionCategory.objects.filter(
                owner__isnull=True
            )
        }
        strays = sorted(
            target
            for target in BOFA_CATEGORY_MAP.values()
            if target is not None and target.casefold() not in canonical
        )
        assert strays == []
