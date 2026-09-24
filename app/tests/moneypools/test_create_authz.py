"""Tests for ownership scoping on the create path of the moneypools API.

Covers the create endpoints whose request body names a bank account
(budgets, transactions, internal transactions) under both interactive
(JWT) and machine (API key) authentication, plus the defense-in-depth
check in `AccountOwnerQuerySetMixin` and the `funding_type` default on
budget create.
"""

# system imports
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

# 3rd party imports
import pytest
from django.urls import reverse
from djmoney.money import Money
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

# Project imports
from config.api_router import router
from moneypools.api.v1.views import BudgetViewSet, TransactionCategoryViewSet
from moneypools.models import (
    BankAccount,
    Budget,
    InternalTransaction,
    Transaction,
)
from moneypools.permissions import (
    AccountOwnerCreateMixin,
    AccountOwnerQuerySetMixin,
)
from users.models import APIKey, User

pytestmark = pytest.mark.django_db


####################################################################
#
def _budget_payload(account: BankAccount, budgets: list[Budget]) -> dict:
    """Build a minimal budget create body for `account`."""
    return {
        "name": "Groceries",
        "bank_account": str(account.id),
        "budget_type": "G",
        "funding_type": "D",
        "target_balance": "100.00",
    }


####################################################################
#
def _transaction_payload(account: BankAccount, budgets: list[Budget]) -> dict:
    """Build a minimal transaction create body for `account`."""
    return {
        "bank_account": str(account.id),
        "amount": "-5.00",
        "posted_date": "2026-04-01T12:00:00Z",
        "transaction_type": "signature_purchase",
        "raw_description": "COFFEE SHOP",
    }


####################################################################
#
def _internal_transaction_payload(
    account: BankAccount, budgets: list[Budget]
) -> dict:
    """Build a transfer body between two of `account`'s budgets."""
    src, dst = budgets
    return {
        "bank_account": str(account.id),
        "amount": "10.00",
        "src_budget": str(src.id),
        "dst_budget": str(dst.id),
    }


# Each case names the create route, the payload builder, and the model
# whose rows on the target account must not grow on rejection.
#
CREATE_ENDPOINTS = [
    pytest.param("api_v1:budget-list", _budget_payload, Budget, id="budget"),
    pytest.param(
        "api_v1:transaction-list",
        _transaction_payload,
        Transaction,
        id="transaction",
    ),
    pytest.param(
        "api_v1:internaltransaction-list",
        _internal_transaction_payload,
        InternalTransaction,
        id="internal-transaction",
    ),
]

AUTH_MODES = ["jwt", "api_key"]


####################################################################
#
def _client_for(user: User, auth_mode: str) -> APIClient:
    """Return a client authenticated as `user` via `auth_mode`.

    Args:
        user: The user the client acts as.
        auth_mode: `"jwt"` for an interactive (force-authenticated)
            session, `"api_key"` for an `Authorization: Api-Key` header.

    Returns:
        An authenticated `APIClient`.
    """
    client = APIClient()
    if auth_mode == "api_key":
        _, plaintext = APIKey.make(user, "create authz test")
        client.credentials(HTTP_AUTHORIZATION=f"Api-Key {plaintext}")
    else:
        client.force_authenticate(user=user)
    return client


####################################################################
#
def _account_with_budgets(
    owner: User,
    bank_account_factory: Callable[..., BankAccount],
    budget_factory: Callable[..., Budget],
) -> tuple[BankAccount, list[Budget]]:
    """Create an account owned by `owner` with a funded and an empty budget."""
    account = bank_account_factory(owners=[owner])
    src = budget_factory(bank_account=account, balance=Money(500, "USD"))
    dst = budget_factory(bank_account=account)
    return account, [src, dst]


########################################################################
########################################################################
#
class TestCreateScopedToOwnedAccounts:
    """Create endpoints accept only bank accounts the caller owns."""

    ####################################################################
    #
    @pytest.mark.parametrize("auth_mode", AUTH_MODES)
    @pytest.mark.parametrize("url_name,build_payload,model", CREATE_ENDPOINTS)
    def test_create_in_unowned_account_rejected(
        self,
        user: User,
        user_factory: Callable[..., User],
        bank_account_factory: Callable[..., BankAccount],
        budget_factory: Callable[..., Budget],
        url_name: str,
        build_payload: Callable[[BankAccount, list[Budget]], dict],
        model: type[Budget | Transaction | InternalTransaction],
        auth_mode: str,
    ) -> None:
        """
        GIVEN: a bank account (with budgets) owned by another user
        WHEN:  the caller creates a budget, transaction or internal
               transaction naming that account, authenticated either
               interactively or with an API key
        THEN:  400 Bad Request is returned with the same "does not
               exist" error a nonexistent account produces
        AND:   the account's posted and available balances are unchanged
        AND:   no object is created on that account
        AND:   the account's budget balances are unchanged
        """
        victim, victim_budgets = _account_with_budgets(
            user_factory(), bank_account_factory, budget_factory
        )
        posted_before = victim.posted_balance
        available_before = victim.available_balance
        budget_balances_before = {
            b.id: b.balance for b in Budget.objects.filter(bank_account=victim)
        }
        count_before = model.objects.filter(bank_account=victim).count()

        client = _client_for(user, auth_mode)
        response = client.post(
            reverse(url_name),
            build_payload(victim, victim_budgets),
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "bank_account" in response.data
        assert "does not exist" in str(response.data["bank_account"][0])

        victim.refresh_from_db()
        assert victim.posted_balance == posted_before
        assert victim.available_balance == available_before
        assert model.objects.filter(bank_account=victim).count() == (
            count_before
        )
        budget_balances_after = {
            b.id: b.balance for b in Budget.objects.filter(bank_account=victim)
        }
        assert budget_balances_after == budget_balances_before

    ####################################################################
    #
    @pytest.mark.parametrize("auth_mode", AUTH_MODES)
    @pytest.mark.parametrize("url_name,build_payload,model", CREATE_ENDPOINTS)
    def test_create_in_owned_account_succeeds(
        self,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
        budget_factory: Callable[..., Budget],
        url_name: str,
        build_payload: Callable[[BankAccount, list[Budget]], dict],
        model: type[Budget | Transaction | InternalTransaction],
        auth_mode: str,
    ) -> None:
        """
        GIVEN: a bank account (with budgets) owned by the caller
        WHEN:  the caller creates a budget, transaction or internal
               transaction naming that account, authenticated either
               interactively or with an API key
        THEN:  201 Created is returned
        AND:   the new object belongs to that account
        """
        account, budgets = _account_with_budgets(
            user, bank_account_factory, budget_factory
        )

        client = _client_for(user, auth_mode)
        response = client.post(
            reverse(url_name),
            build_payload(account, budgets),
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        created = model.objects.get(id=response.data["id"])
        assert created.bank_account == account

    ####################################################################
    #
    @pytest.mark.parametrize("auth_mode", AUTH_MODES)
    def test_budget_fillup_goal_not_writable(
        self,
        user: User,
        user_factory: Callable[..., User],
        bank_account_factory: Callable[..., BankAccount],
        budget_factory: Callable[..., Budget],
        auth_mode: str,
    ) -> None:
        """
        GIVEN: a budget owned by another user
        WHEN:  the caller creates a budget in their own account naming
               that budget as `fillup_goal`
        THEN:  the budget is created without that link -- `fillup_goal`
               is managed by the budget service, not the request body
        """
        other_account = bank_account_factory(owners=[user_factory()])
        other_budget = budget_factory(bank_account=other_account)
        account = bank_account_factory(owners=[user])

        client = _client_for(user, auth_mode)
        response = client.post(
            reverse("api_v1:budget-list"),
            {
                "name": "Groceries",
                "bank_account": str(account.id),
                "budget_type": "G",
                "funding_type": "D",
                "target_balance": "100.00",
                "fillup_goal": str(other_budget.id),
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        created = Budget.objects.get(id=response.data["id"])
        assert created.fillup_goal_id is None


########################################################################
########################################################################
#
class TestCreateOwnershipDefenseInDepth:
    """`AccountOwnerQuerySetMixin` re-checks related-object ownership."""

    ####################################################################
    #
    @staticmethod
    def _view_for(user: User) -> BudgetViewSet:
        """Return a `BudgetViewSet` bound to a request for `user`."""
        # `check_create_ownership` reads only `self.request.user`, so a
        # minimal stand-in request is enough to exercise it directly.
        #
        view = BudgetViewSet()
        view.request = SimpleNamespace(user=user)
        return view

    ####################################################################
    #
    def test_create_capable_owned_viewsets_use_create_mixin(self) -> None:
        """
        GIVEN: the v1 router's registered viewsets
        WHEN:  a moneypools viewset scopes its queryset by account
               ownership and exposes create
        THEN:  it includes `AccountOwnerCreateMixin`, so create re-checks
               related-object ownership
        AND:   no read-only owned viewset gains a create route from it
        """
        # `TransactionCategoryViewSet` is not account-owned (categories
        # use `visible_to`), so it has no `AccountOwnerQuerySetMixin`
        # and falls outside this check; listed to keep that explicit.
        #
        owned = [
            viewset
            for _, viewset, _ in router.registry
            if issubclass(viewset, AccountOwnerQuerySetMixin)
        ]
        assert owned
        assert not issubclass(
            TransactionCategoryViewSet, AccountOwnerQuerySetMixin
        )
        for viewset in owned:
            has_create = hasattr(viewset, "create")
            uses_mixin = issubclass(viewset, AccountOwnerCreateMixin)
            assert has_create == uses_mixin, viewset.__name__

    ####################################################################
    #
    def test_unowned_related_object_denied(
        self,
        user: User,
        user_factory: Callable[..., User],
        bank_account_factory: Callable[..., BankAccount],
        budget_factory: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: validated create data naming an account and a budget that
               belong to another user (as an unscoped serializer field
               would produce)
        WHEN:  the view's create-path ownership check runs
        THEN:  the request is denied with 403 Permission Denied
        """
        victim = bank_account_factory(owners=[user_factory()])
        victim_budget = budget_factory(bank_account=victim)
        view = self._view_for(user)

        data: dict[str, Any] = {"bank_account": victim, "name": "x"}
        with pytest.raises(PermissionDenied):
            view.check_create_ownership(data)

        data = {"src_budget": victim_budget}
        with pytest.raises(PermissionDenied):
            view.check_create_ownership(data)

        # A `many=True` related field validates to a list of instances.
        #
        data = {"budgets": [victim_budget]}
        with pytest.raises(PermissionDenied):
            view.check_create_ownership(data)

    ####################################################################
    #
    def test_owned_related_objects_allowed(
        self,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
        budget_factory: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: validated create data naming the caller's own account and
               budget, plus values that are not account-owned
        WHEN:  the view's create-path ownership check runs
        THEN:  the check passes
        """
        account = bank_account_factory(owners=[user])
        budget = budget_factory(bank_account=account)
        view = self._view_for(user)

        view.check_create_ownership(
            {
                "bank_account": account,
                "src_budget": budget,
                "bank": account.bank,
                "banks": [account.bank],
                "budgets": [budget],
                "name": "x",
            }
        )


########################################################################
########################################################################
#
class TestBudgetCreateFundingTypeDefault:
    """Budget create applies the model's `funding_type` default."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "omitted",
        [("funding_type",), ("funding_type", "budget_type")],
        ids=["funding-type", "funding-and-budget-type"],
    )
    def test_omitted_funding_type_uses_default(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
        omitted: tuple[str, ...],
    ) -> None:
        """
        GIVEN: a budget create body without `funding_type` (and
               optionally without `budget_type`)
        WHEN:  POST /api/v1/budgets/
        THEN:  201 Created is returned, never a server error
        AND:   the budget has the documented defaults: Goal budget type
               and Target Date funding type
        """
        account = bank_account_factory(owners=[user])
        payload = {
            "name": "Vacation",
            "bank_account": str(account.id),
            "budget_type": "G",
            "funding_type": "D",
            "target_balance": "100.00",
        }
        for key in omitted:
            payload.pop(key)

        response = auth_client.post(
            reverse("api_v1:budget-list"), payload, format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED
        budget = Budget.objects.get(id=response.data["id"])
        assert budget.budget_type == Budget.BudgetType.GOAL
        assert budget.funding_type == Budget.FundingType.TARGET_DATE
