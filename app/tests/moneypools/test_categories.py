#!/usr/bin/env python
#
"""Tests for TransactionCategory: model, resolver, visibility, and API."""

# system imports
from collections.abc import Callable
from io import StringIO

# 3rd party imports
import pytest
import yaml
from django.core.management import call_command
from django.db import IntegrityError
from django.db import transaction as db_transaction
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

# Project imports
from moneypools.management.commands.import_bank_account import (
    _resolve_category,
)
from moneypools.models import (
    BankAccount,
    Budget,
    Transaction,
    TransactionCategory,
    TransactionCategoryAlias,
)
from moneypools.service import categories as categories_svc
from moneypools.service import (
    transaction_allocation as transaction_allocation_svc,
)
from users.models import User

pytestmark = pytest.mark.django_db


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
            ("Food & Drink:Groceries", ("Food & Drink", "Groceries")),
            ("Food & Drink : Groceries", ("Food & Drink", "Groceries")),
            (
                "  Education:  Tuition   & Fees ",
                ("Education", "Tuition & Fees"),
            ),
            ("Groceries : Groceries", ("Groceries", "Groceries")),
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
        other = user_factory()
        c1 = TransactionCategory.objects.create(
            group="Hobbies", name="Kites", owner=user
        )
        c2 = TransactionCategory.objects.create(
            group="Hobbies", name="Kites", owner=other
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
    ) -> None:
        """
        GIVEN: two users co-owning a bank account
        WHEN:  one creates a custom category
        THEN:  the co-owner can see it
        """
        other = user_factory()
        bank_account_factory(owners=[user, other])
        theirs = TransactionCategory.objects.create(
            group="Shared", name="Thing", owner=other
        )
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
    ) -> None:
        """
        GIVEN: a co-owner's category referenced by a transaction on the
               shared account, then the co-owner is removed
        WHEN:  visibility is recomputed
        THEN:  the referenced category stays visible (grandfathered)
        """
        other = user_factory()
        account = bank_account_factory(owners=[user, other])
        category = TransactionCategory.objects.create(
            group="Grandfather", name="Thing", owner=other
        )
        tx = transaction_factory(bank_account=account)
        tx.category = category
        tx.save(update_fields=["category"])

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
    @pytest.mark.parametrize("explicit", [False, True])
    def test_category_at_allocation_creation(
        self,
        explicit: bool,
        bank_account_factory: Callable[..., BankAccount],
        budget_factory: Callable[..., Budget],
        transaction_factory: Callable[..., Transaction],
        transaction_category_factory: Callable[..., TransactionCategory],
    ) -> None:
        """
        GIVEN: a transaction with a category
        WHEN:  an allocation is created, with or without an explicit category
        THEN:  an explicit category wins; otherwise the transaction's is copied
        """
        account = bank_account_factory()
        tx_category = transaction_category_factory(name="TxCat")
        tx = transaction_factory(bank_account=account)
        tx.category = tx_category
        tx.save(update_fields=["category"])
        budget = budget_factory(bank_account=account)

        kwargs = {}
        expected = tx_category
        if explicit:
            expected = transaction_category_factory(name="AllocCat")
            kwargs["category"] = expected

        allocation = transaction_allocation_svc.create(
            transaction=tx, budget=budget, amount=tx.amount, **kwargs
        )
        # The category FK uses to_field="id", so category_id is the UUID.
        assert allocation.category_id == expected.id


########################################################################
########################################################################
#
class TestResolver:
    """Tests for the provider category resolver.

    The resolver relies on the global rows seeded by migration 0038.
    """

    ################################################################
    #
    def test_exact_full_name_match(self) -> None:
        """
        GIVEN: a raw string matching a seeded global full name
        WHEN:  it is resolved
        THEN:  the existing global row is returned
        """
        category = categories_svc.resolve_category_string(
            "Food & Drink:Groceries"
        )
        assert category is not None
        assert (category.group, category.name) == (
            "Food & Drink",
            "Groceries",
        )
        assert category.owner_id is None

    ################################################################
    #
    def test_unique_subname_match(self) -> None:
        """
        GIVEN: a raw string whose name uniquely matches one global row and
               is not itself a group name
        WHEN:  it is resolved
        THEN:  that row is returned
        """
        category = categories_svc.resolve_category_string(
            "Groceries : Groceries"
        )
        assert category is not None
        assert (category.group, category.name) == (
            "Food & Drink",
            "Groceries",
        )

    ################################################################
    #
    def test_subname_guard_creates_top_level(self) -> None:
        """
        GIVEN: BofA's 'Travel : Travel' where 'Travel' is also a group name
        WHEN:  it is resolved
        THEN:  the sub-name guard fires and a new top-level 'Travel :
               Travel' global row is created (NOT mapped to Business:Travel)
        """
        category = categories_svc.resolve_category_string("Travel : Travel")
        assert category is not None
        assert (category.group, category.name) == ("Travel", "Travel")
        assert category.owner_id is None

    ################################################################
    #
    def test_auto_create_for_unknown(self) -> None:
        """
        GIVEN: a raw string matching nothing
        WHEN:  it is resolved
        THEN:  a new global row is created
        """
        category = categories_svc.resolve_category_string("Nonsense : Widget")
        assert category is not None
        assert category.owner_id is None
        assert (category.group, category.name) == ("Nonsense", "Widget")

    ################################################################
    #
    def test_provider_alias_lookup_wins(self) -> None:
        """
        GIVEN: an alias mapping a provider string to a chosen category
        WHEN:  the provider string is resolved
        THEN:  the alias target is returned even though sub-name matching
               would have chosen differently
        """
        target = TransactionCategory.objects.get(
            owner__isnull=True, group="Uncategorized", name="Other Shopping"
        )
        TransactionCategoryAlias.objects.create(
            provider="bofa",
            alias_key="groceries:groceries",
            category=target,
        )
        resolved = categories_svc.resolve_provider_category(
            "bofa", "Groceries : Groceries"
        )
        assert resolved is not None
        assert resolved.pkid == target.pkid

    ################################################################
    #
    def test_provider_resolution_writes_alias(self) -> None:
        """
        GIVEN: no alias for a provider string
        WHEN:  it is resolved via the provider resolver
        THEN:  an alias row is written so it can be re-pointed later
        """
        categories_svc.resolve_provider_category(
            "bofa", "Food & Drink : Groceries"
        )
        assert TransactionCategoryAlias.objects.filter(
            provider="bofa", alias_key="food & drink:groceries"
        ).exists()

    ################################################################
    #
    @pytest.mark.parametrize("raw", ["", "   ", None])
    def test_blank_resolves_to_none(self, raw: str | None) -> None:
        """
        GIVEN: a blank/empty raw string
        WHEN:  it is resolved
        THEN:  None (unassigned) is returned
        """
        assert categories_svc.resolve_category_string(raw or "") is None


########################################################################
########################################################################
#
class TestCategoryAPI:
    """Tests for the transaction-categories REST endpoint."""

    ################################################################
    #
    def test_list_requires_auth(self) -> None:
        """
        GIVEN: an unauthenticated client
        WHEN:  it lists categories
        THEN:  the request is rejected
        """
        response = APIClient().get(reverse("api_v1:transaction-category-list"))
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    ################################################################
    #
    def test_list_scopes(
        self,
        auth_client: APIClient,
        user: User,
        user_factory: Callable[..., User],
    ) -> None:
        """
        GIVEN: an own category and an unrelated user's category
        WHEN:  the user lists with scope=mine
        THEN:  own appears; the stranger's does not
        """
        mine = TransactionCategory.objects.create(
            group="Mine", name="Thing", owner=user
        )
        stranger = TransactionCategory.objects.create(
            group="Stranger", name="Thing", owner=user_factory()
        )
        response = auth_client.get(
            reverse("api_v1:transaction-category-list"),
            {"scope": "mine"},
        )
        assert response.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in response.data["results"]}
        assert str(mine.id) in ids
        assert str(stranger.id) not in ids

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
        assert category.owner_id == user.pk
        assert (category.group, category.name) == ("Custom Group", "My Cat")

    ################################################################
    #
    @pytest.mark.parametrize("scope", ["global", "own"])
    def test_create_rejects_case_insensitive_duplicate(
        self, auth_client: APIClient, user: User, scope: str
    ) -> None:
        """
        GIVEN: an existing global or own category
        WHEN:  the user creates a case-insensitive duplicate
        THEN:  it is rejected
        """
        if scope == "global":
            group, name = "food & drink", "groceries"  # dup of a seeded row
        else:
            TransactionCategory.objects.create(
                group="Owned", name="Thing", owner=user
            )
            group, name = "owned", "thing"
        response = auth_client.post(
            reverse("api_v1:transaction-category-list"),
            {"group": group, "name": name},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    ################################################################
    #
    @pytest.mark.parametrize("method", ["patch", "delete"])
    def test_global_rows_immutable_via_api(
        self, auth_client: APIClient, method: str
    ) -> None:
        """
        GIVEN: a global category
        WHEN:  a user tries to modify or delete it
        THEN:  it is forbidden (global rows are admin-managed)
        """
        category = TransactionCategory.objects.get(
            owner__isnull=True, group="Food & Drink", name="Groceries"
        )
        url = reverse(
            "api_v1:transaction-category-detail", kwargs={"id": category.id}
        )
        response = getattr(auth_client, method)(
            url, {"name": "Renamed"} if method == "patch" else None
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    ################################################################
    #
    @pytest.mark.parametrize(
        "referenced,expected",
        [
            (True, status.HTTP_409_CONFLICT),
            (False, status.HTTP_204_NO_CONTENT),
        ],
    )
    def test_owner_delete_blocked_when_referenced(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
        referenced: bool,
        expected: int,
    ) -> None:
        """
        GIVEN: an owned category, optionally referenced by a transaction
        WHEN:  the owner deletes it
        THEN:  a referenced category returns 409; an unreferenced one deletes
        """
        category = TransactionCategory.objects.create(
            group="Owned", name="Target", owner=user
        )
        if referenced:
            account = bank_account_factory(owners=[user])
            tx = transaction_factory(bank_account=account)
            tx.category = category
            tx.save(update_fields=["category"])

        url = reverse(
            "api_v1:transaction-category-detail", kwargs={"id": category.id}
        )
        response = auth_client.delete(url)
        assert response.status_code == expected
        assert (
            TransactionCategory.objects.filter(pk=category.pkid).exists()
            is referenced
        )

    ################################################################
    #
    def test_archive_action(self, auth_client: APIClient, user: User) -> None:
        """
        GIVEN: an owned category
        WHEN:  the owner archives it
        THEN:  it is marked archived
        """
        category = TransactionCategory.objects.create(
            group="Owned", name="ToArchive", owner=user
        )
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
    def test_category_group_and_uncategorized_filters(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
    ) -> None:
        """
        GIVEN: one categorized and one uncategorized transaction
        WHEN:  the transaction list is filtered
        THEN:  category, category_group, and uncategorized narrow correctly
        """
        account = bank_account_factory(owners=[user])
        category = TransactionCategory.objects.get(
            owner__isnull=True, group="Food & Drink", name="Groceries"
        )
        categorized = transaction_factory(bank_account=account)
        categorized.category = category
        categorized.save(update_fields=["category"])
        uncategorized = transaction_factory(bank_account=account)

        url = reverse("api_v1:transaction-list")

        for params in (
            {"category": str(category.id)},
            {"category_group": "food & drink"},
        ):
            ids = {
                row["id"]
                for row in auth_client.get(url, params).data["results"]
            }
            assert str(categorized.id) in ids
            assert str(uncategorized.id) not in ids

        unset = {
            row["id"]
            for row in auth_client.get(url, {"uncategorized": "true"}).data[
                "results"
            ]
        }
        assert str(uncategorized.id) in unset
        assert str(categorized.id) not in unset


########################################################################
########################################################################
#
class TestAutoSpendValidation:
    """Tests for Budget.auto_spend serializer validation."""

    ################################################################
    #
    @pytest.mark.parametrize(
        "entries,expected_status,expected_value",
        [
            (
                ["food & drink:groceries"],
                status.HTTP_201_CREATED,
                ["Food & Drink : Groceries"],
            ),
            (["No Such : Category"], status.HTTP_400_BAD_REQUEST, None),
        ],
    )
    def test_auto_spend_entries(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
        entries: list[str],
        expected_status: int,
        expected_value: list[str] | None,
    ) -> None:
        """
        GIVEN: an auto_spend list of matcher strings
        WHEN:  a budget is created
        THEN:  entries resolving to a visible category are accepted and
               rewritten to canonical full names; others are rejected
        """
        account = bank_account_factory(owners=[user])
        response = auth_client.post(
            reverse("api_v1:budget-list"),
            {
                "name": "Budget",
                "bank_account": str(account.id),
                "budget_type": Budget.BudgetType.GOAL,
                "funding_type": Budget.FundingType.FIXED_AMOUNT,
                "target_balance": "100.00",
                "funding_amount": "10.00",
                "auto_spend": entries,
            },
            format="json",
        )
        assert response.status_code == expected_status, response.data
        if expected_value is not None:
            budget = Budget.objects.get(id=response.data["id"])
            assert budget.auto_spend == expected_value


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
        "raw,expected",
        [
            (None, None),
            ("", None),
            ("Uncategorized:Unassigned", None),  # legacy sentinel -> NULL
            ("Uncategorized : Unassigned", None),
        ],
    )
    def test_blank_and_sentinel_resolve_to_none(
        self, raw: str | None, expected: None
    ) -> None:
        """
        GIVEN: a blank value or the legacy unassigned sentinel
        WHEN:  it is resolved during import
        THEN:  it maps to None (unassigned)
        """
        assert _resolve_category(raw) is expected

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
        assert (category.group, category.name) == (
            "Education",
            "Tuition & Fees",
        )
        assert category.owner_id is None


########################################################################
########################################################################
#
class TestSeedCategoryAliases:
    """Tests for the seed_category_aliases management command."""

    ################################################################
    #
    def _write(self, tmp_path, entries: list[dict]) -> str:
        path = tmp_path / "aliases.yaml"
        path.write_text(
            yaml.safe_dump({"provider": "bofa", "categories": entries}),
            encoding="utf-8",
        )
        return str(path)

    ################################################################
    #
    def test_seeds_aliases_and_creates_missing_category(self, tmp_path) -> None:
        """
        GIVEN: a reviewed file mapping a provider string to a new category
        WHEN:  seed_category_aliases loads it
        THEN:  the alias is created and the target category is created global
        """
        path = self._write(
            tmp_path,
            [
                {
                    "alias_key": "insurance:insurance",
                    "category": "Insurance : Insurance",
                }
            ],
        )
        call_command("seed_category_aliases", path, stdout=StringIO())

        alias = TransactionCategoryAlias.objects.get(
            provider="bofa", alias_key="insurance:insurance"
        )
        assert alias.category.full_name == "Insurance : Insurance"
        assert alias.category.owner_id is None

    ################################################################
    #
    def test_reload_is_idempotent(self, tmp_path) -> None:
        """
        GIVEN: an alias already seeded from a file
        WHEN:  the same file is loaded again
        THEN:  the alias is left unchanged (not spuriously re-saved)
        """
        path = self._write(
            tmp_path,
            [
                {
                    "alias_key": "groceries:groceries",
                    "category": "Food & Drink : Groceries",
                }
            ],
        )
        call_command("seed_category_aliases", path, stdout=StringIO())
        alias = TransactionCategoryAlias.objects.get(
            provider="bofa", alias_key="groceries:groceries"
        )
        first_modified = alias.modified_at

        out = StringIO()
        call_command("seed_category_aliases", path, stdout=out)
        alias.refresh_from_db()
        # The unchanged path must be taken -- no re-save on reload.
        assert alias.modified_at == first_modified
        assert "1 unchanged" in out.getvalue()
