"""Tests for the moneypools REST API: serializers, views, and permissions."""

# system imports
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

# 3rd party imports
import pytest
from django.urls import reverse
from djmoney.money import Money
from rest_framework import status
from rest_framework.test import APIClient

# Project imports
from moneypools.models import (
    Bank,
    BankAccount,
    Budget,
    InternalTransaction,
    Transaction,
    TransactionAllocation,
)
from tests.moneypools.factories import (
    BankAccountFactory,
    BudgetFactory,
    TransactionFactory,
)
from users.models import User

pytestmark = pytest.mark.django_db


####################################################################
#
@pytest.fixture
def api_client() -> APIClient:
    """Return an unauthenticated DRF test client."""
    return APIClient()


####################################################################
#
@pytest.fixture
def auth_client(user: User) -> APIClient:
    """Return a DRF test client authenticated as the default user."""
    client = APIClient()
    client.force_authenticate(user=user)
    return client


########################################################################
########################################################################
#
class TestCurrenciesAPI:
    """Tests for the /api/v1/currencies/ endpoint."""

    ####################################################################
    #
    def test_list_requires_auth(self, api_client: APIClient) -> None:
        """
        GIVEN: an unauthenticated client
        WHEN:  GET /api/v1/currencies/
        THEN:  401 Unauthorized is returned
        """
        response = api_client.get(reverse("api_v1:currencies"))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    ####################################################################
    #
    def test_list_currencies(self, auth_client: APIClient) -> None:
        """
        GIVEN: an authenticated client
        WHEN:  GET /api/v1/currencies/
        THEN:  a list of currency objects is returned, each with code,
               name, and numeric fields, sorted by code
        """
        response = auth_client.get(reverse("api_v1:currencies"))
        assert response.status_code == status.HTTP_200_OK
        assert isinstance(response.data, list)
        assert len(response.data) > 0
        usd = next(c for c in response.data if c["code"] == "USD")
        assert usd["name"] == "US Dollar"
        assert usd["numeric"] == "840"
        codes = [c["code"] for c in response.data]
        assert codes == sorted(codes)


########################################################################
########################################################################
#
class TestBankAPI:
    """Tests for the read-only /api/v1/banks/ endpoint."""

    ####################################################################
    #
    def test_list_requires_auth(self, api_client: APIClient) -> None:
        """
        GIVEN: an unauthenticated client
        WHEN:  GET /api/v1/banks/
        THEN:  401 Unauthorized is returned
        """
        response = api_client.get(reverse("api_v1:bank-list"))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    ####################################################################
    #
    def test_list_banks(
        self,
        auth_client: APIClient,
        bank_factory: Callable[..., Bank],
    ) -> None:
        """
        GIVEN: two banks exist
        WHEN:  GET /api/v1/banks/
        THEN:  both banks are returned with expected fields
        """
        bank_factory()
        bank_factory()
        response = auth_client.get(reverse("api_v1:bank-list"))
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 2
        bank_data = response.data["results"][0]
        assert "id" in bank_data
        assert "name" in bank_data
        assert "default_currency" in bank_data

    ####################################################################
    #
    def test_retrieve_bank(
        self,
        auth_client: APIClient,
        bank_factory: Callable[..., Bank],
    ) -> None:
        """
        GIVEN: a bank exists
        WHEN:  GET /api/v1/banks/<uuid>/
        THEN:  the bank detail is returned
        """
        bank = bank_factory()
        response = auth_client.get(
            reverse("api_v1:bank-detail", kwargs={"id": bank.id})
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == bank.name

    ####################################################################
    #
    def test_create_not_allowed(self, auth_client: APIClient) -> None:
        """
        GIVEN: an authenticated client
        WHEN:  POST /api/v1/banks/
        THEN:  405 Method Not Allowed is returned
        """
        response = auth_client.post(
            reverse("api_v1:bank-list"),
            {"name": "New Bank"},
        )
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


########################################################################
########################################################################
#
class TestBankAccountAPI:
    """Tests for the /api/v1/bank-accounts/ endpoint."""

    ####################################################################
    #
    def test_create_account(
        self,
        auth_client: APIClient,
        user: User,
        bank_factory: Callable[..., Bank],
    ) -> None:
        """
        GIVEN: a bank exists and an authenticated user
        WHEN:  POST /api/v1/bank-accounts/ with name, bank, and account_type
        THEN:  the account is created and the user is added as owner
        """
        bank = bank_factory()
        response = auth_client.post(
            reverse("api_v1:bankaccount-list"),
            {
                "name": "My Checking",
                "bank": str(bank.id),
                "account_type": "C",
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["name"] == "My Checking"
        assert response.data["unallocated_budget"] is not None

        # User should be an owner.
        #
        account = BankAccount.objects.get(id=response.data["id"])
        assert user in account.owners.all()

    ####################################################################
    #
    def test_create_account_with_initial_balance(
        self,
        auth_client: APIClient,
        bank_factory: Callable[..., Bank],
    ) -> None:
        """
        GIVEN: a bank exists
        WHEN:  POST /api/v1/bank-accounts/ with available_balance set
        THEN:  the account is created with the specified balance and
               the unallocated budget receives that balance
        """
        bank = bank_factory()
        response = auth_client.post(
            reverse("api_v1:bankaccount-list"),
            {
                "name": "Savings",
                "bank": str(bank.id),
                "account_type": "S",
                "available_balance": "1500.00",
            },
        )
        assert response.status_code == status.HTTP_201_CREATED

        account = BankAccount.objects.get(id=response.data["id"])
        assert account.available_balance.amount == Decimal("1500.00")

        # The unallocated budget should have the initial balance.
        #
        unalloc = account.unallocated_budget
        assert unalloc is not None
        assert unalloc.balance.amount == Decimal("1500.00")

    ####################################################################
    #
    def test_create_account_with_currency(
        self,
        auth_client: APIClient,
        bank_factory: Callable[..., Bank],
    ) -> None:
        """
        GIVEN: a bank exists
        WHEN:  POST /api/v1/bank-accounts/ with currency=EUR
        THEN:  the account and its balances use EUR
        """
        bank = bank_factory()
        response = auth_client.post(
            reverse("api_v1:bankaccount-list"),
            {
                "name": "Euro Account",
                "bank": str(bank.id),
                "account_type": "C",
                "currency": "EUR",
            },
        )
        assert response.status_code == status.HTTP_201_CREATED

        account = BankAccount.objects.get(id=response.data["id"])
        assert account.currency == "EUR"
        assert str(account.posted_balance_currency) == "EUR"  # type: ignore[attr-defined]

    ####################################################################
    #
    def test_currency_immutable_after_create(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: an existing bank account
        WHEN:  PATCH /api/v1/bank-accounts/<uuid>/ with a different currency
        THEN:  400 Bad Request with a currency validation error
        """
        account = bank_account_factory(owners=[user])
        response = auth_client.patch(
            reverse(
                "api_v1:bankaccount-detail",
                kwargs={"id": account.id},
            ),
            {"currency": "GBP"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "currency" in response.data

    ####################################################################
    #
    def test_list_only_owned_accounts(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: two accounts exist -- one owned by the user, one by another
        WHEN:  GET /api/v1/bank-accounts/
        THEN:  only the owned account is returned
        """
        bank_account_factory(owners=[user])
        bank_account_factory()  # owned by a different user
        response = auth_client.get(reverse("api_v1:bankaccount-list"))
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1

    ####################################################################
    #
    def test_update_name(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: an existing bank account
        WHEN:  PATCH /api/v1/bank-accounts/<uuid>/ with a new name
        THEN:  the name is updated
        """
        account = bank_account_factory(owners=[user])
        response = auth_client.patch(
            reverse(
                "api_v1:bankaccount-detail",
                kwargs={"id": account.id},
            ),
            {"name": "Renamed Account"},
        )
        assert response.status_code == status.HTTP_200_OK
        account.refresh_from_db()
        assert account.name == "Renamed Account"


########################################################################
########################################################################
#
class TestBudgetAPI:
    """Tests for the /api/v1/budgets/ endpoint."""

    ####################################################################
    #
    def test_create_budget(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: an owned bank account
        WHEN:  POST /api/v1/budgets/ with required fields
        THEN:  a new budget is created under that account
        """
        account = bank_account_factory(owners=[user])
        response = auth_client.post(
            reverse("api_v1:budget-list"),
            {
                "name": "Groceries",
                "bank_account": str(account.id),
                "budget_type": "R",
                "funding_type": "F",
                "target_balance": "500.00",
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["name"] == "Groceries"
        assert str(response.data["bank_account"]) == str(account.id)

    ####################################################################
    #
    def test_list_budgets_filtered_by_account(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
        budget_factory: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: budgets on two different owned accounts
        WHEN:  GET /api/v1/budgets/?bank_account=<uuid>
        THEN:  only budgets for the specified account are returned
        """
        acct1 = bank_account_factory(owners=[user])
        acct2 = bank_account_factory(owners=[user])
        budget_factory(bank_account=acct1)
        budget_factory(bank_account=acct2)

        response = auth_client.get(
            reverse("api_v1:budget-list"),
            {"bank_account": str(acct1.id)},
        )
        assert response.status_code == status.HTTP_200_OK
        # acct1 has the auto-created unallocated budget + the one we made
        #
        for budget in response.data["results"]:
            assert str(budget["bank_account"]) == str(acct1.id)

    ####################################################################
    #
    def test_cannot_delete_unallocated_budget(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: an account's unallocated budget
        WHEN:  DELETE /api/v1/budgets/<uuid>/
        THEN:  403 Forbidden is returned
        """
        account = bank_account_factory(owners=[user])
        unalloc = account.unallocated_budget
        assert unalloc is not None
        response = auth_client.delete(
            reverse(
                "api_v1:budget-detail",
                kwargs={"id": unalloc.id},
            ),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    ####################################################################
    #
    def test_cannot_rename_unallocated_budget(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: an account's unallocated budget
        WHEN:  PATCH /api/v1/budgets/<uuid>/ with a new name
        THEN:  400 Bad Request with a name validation error
        """
        account = bank_account_factory(owners=[user])
        unalloc = account.unallocated_budget
        assert unalloc is not None
        response = auth_client.patch(
            reverse(
                "api_v1:budget-detail",
                kwargs={"id": unalloc.id},
            ),
            {"name": "Sneaky Rename"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "name" in response.data

    ####################################################################
    #
    def test_budget_type_immutable(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
        budget_factory: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: an existing budget with type Goal
        WHEN:  PATCH with budget_type=R
        THEN:  400 Bad Request is returned
        """
        account = bank_account_factory(owners=[user])
        budget = budget_factory(bank_account=account, budget_type="G")
        response = auth_client.patch(
            reverse("api_v1:budget-detail", kwargs={"id": budget.id}),
            {"budget_type": "R"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "budget_type" in response.data

    ####################################################################
    #
    def test_delete_blocked_when_budget_has_allocations(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
        budget_factory: Callable[..., Budget],
        transaction_factory: Callable[..., Transaction],
        transaction_allocation_factory: Callable[..., TransactionAllocation],
    ) -> None:
        """
        GIVEN: a budget with at least one transaction allocation
        WHEN:  DELETE /api/v1/budgets/<uuid>/
        THEN:  400 Bad Request is returned and the budget still exists
        """
        account = bank_account_factory(owners=[user])
        budget = budget_factory(bank_account=account)
        txn = transaction_factory(bank_account=account, amount=-50)
        transaction_allocation_factory(
            transaction=txn, budget=budget, amount=-50
        )

        response = auth_client.delete(
            reverse("api_v1:budget-detail", kwargs={"id": budget.id})
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Budget.objects.filter(id=budget.id).exists()

    ####################################################################
    #
    def test_delete_allowed_when_budget_has_no_allocations(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
        budget_factory: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: a budget with no transaction allocations
        WHEN:  DELETE /api/v1/budgets/<uuid>/
        THEN:  204 No Content is returned and the budget no longer exists
        """
        account = bank_account_factory(owners=[user])
        budget = budget_factory(bank_account=account)

        response = auth_client.delete(
            reverse("api_v1:budget-detail", kwargs={"id": budget.id})
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not Budget.objects.filter(id=budget.id).exists()

    ####################################################################
    #
    def test_archive_moves_balance_to_unallocated(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
        budget_factory: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: a budget with a non-zero balance
        WHEN:  POST /api/v1/budgets/<uuid>/archive/
        THEN:  200 OK, budget is archived, its balance is moved to unallocated,
               and archived_at is set
        """
        account = bank_account_factory(owners=[user])
        budget = budget_factory(bank_account=account, balance=300)
        assert account.unallocated_budget is not None
        unalloc_balance_before = account.unallocated_budget.balance

        response = auth_client.post(
            reverse("api_v1:budget-archive", kwargs={"id": budget.id})
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["archived"] is True
        assert response.data["archived_at"] is not None

        assert account.unallocated_budget is not None
        unalloc = Budget.objects.get(id=account.unallocated_budget.id)
        assert unalloc.balance == unalloc_balance_before + budget.balance

    ####################################################################
    #
    def test_archive_also_archives_fillup_goal(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
        budget_factory: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: a Recurring budget with a fill-up goal (both with balances)
        WHEN:  POST /api/v1/budgets/<uuid>/archive/
        THEN:  both the budget and its fill-up goal are archived, and both
               balances are moved to unallocated
        """
        from moneyed import USD, Money

        account = bank_account_factory(owners=[user])
        budget = budget_factory(
            bank_account=account,
            budget_type="R",
            with_fillup_goal=True,
            balance=200,
        )
        budget.refresh_from_db()
        fillup = budget.fillup_goal
        assert fillup is not None
        fillup.balance = Money(100, USD)
        fillup.save()

        assert account.unallocated_budget is not None
        unalloc_balance_before = Budget.objects.get(
            id=account.unallocated_budget.id
        ).balance

        response = auth_client.post(
            reverse("api_v1:budget-archive", kwargs={"id": budget.id})
        )
        assert response.status_code == status.HTTP_200_OK

        fillup.refresh_from_db()
        assert fillup.archived is True

        assert account.unallocated_budget is not None
        unalloc = Budget.objects.get(id=account.unallocated_budget.id)
        assert unalloc.balance == unalloc_balance_before + Money(300, USD)


########################################################################
########################################################################
#
class TestTransactionAPI:
    """Tests for the /api/v1/transactions/ endpoint."""

    ####################################################################
    #
    def test_create_transaction(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: an owned bank account
        WHEN:  POST /api/v1/transactions/ with required fields
        THEN:  a transaction is created and a default allocation to
               the unallocated budget is auto-created
        """
        account = bank_account_factory(owners=[user])
        response = auth_client.post(
            reverse("api_v1:transaction-list"),
            {
                "bank_account": str(account.id),
                "amount": "-45.99",
                "transaction_date": "2026-04-01T12:00:00Z",
                "transaction_type": "signature_purchase",
                "raw_description": "GROCERY STORE #123",
            },
        )
        assert response.status_code == status.HTTP_201_CREATED

        tx = Transaction.objects.get(id=response.data["id"])
        assert tx.amount.amount == Decimal("-45.99")

        # A default allocation should exist.
        #
        allocations = TransactionAllocation.objects.filter(transaction=tx)
        assert allocations.count() == 1
        alloc = allocations.first()
        assert alloc is not None
        assert alloc.budget == account.unallocated_budget

    ####################################################################
    #
    def test_amount_immutable_after_create(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
    ) -> None:
        """
        GIVEN: an existing transaction
        WHEN:  PATCH with a new amount
        THEN:  400 Bad Request is returned
        """
        account = bank_account_factory(owners=[user])
        tx = transaction_factory(bank_account=account)
        response = auth_client.patch(
            reverse("api_v1:transaction-detail", kwargs={"id": tx.id}),
            {"amount": "999.99"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "amount" in response.data

    ####################################################################
    #
    def test_description_updatable(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
    ) -> None:
        """
        GIVEN: an existing transaction
        WHEN:  PATCH with a new description
        THEN:  the description is updated
        """
        account = bank_account_factory(owners=[user])
        tx = transaction_factory(bank_account=account)
        response = auth_client.patch(
            reverse("api_v1:transaction-detail", kwargs={"id": tx.id}),
            {"description": "Cleaned up description"},
        )
        assert response.status_code == status.HTTP_200_OK
        tx.refresh_from_db()
        assert tx.description == "Cleaned up description"

    ####################################################################
    #
    def test_filter_by_date_range(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
    ) -> None:
        """
        GIVEN: transactions on different dates
        WHEN:  GET /api/v1/transactions/?date_from=...&date_to=...
        THEN:  only transactions in the range are returned
        """
        account = bank_account_factory(owners=[user])
        transaction_factory(
            bank_account=account,
            transaction_date="2026-01-15T12:00:00Z",
        )
        transaction_factory(
            bank_account=account,
            transaction_date="2026-03-15T12:00:00Z",
        )
        response = auth_client.get(
            reverse("api_v1:transaction-list"),
            {
                "date_from": "2026-03-01T00:00:00Z",
                "date_to": "2026-04-01T00:00:00Z",
            },
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1

    ####################################################################
    #
    def test_search_by_description(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
    ) -> None:
        """
        GIVEN: transactions with different descriptions
        WHEN:  GET /api/v1/transactions/?search=GROCERY
        THEN:  only matching transactions are returned
        """
        account = bank_account_factory(owners=[user])
        transaction_factory(
            bank_account=account,
            raw_description="GROCERY STORE #123",
        )
        transaction_factory(
            bank_account=account,
            raw_description="GAS STATION #456",
        )
        response = auth_client.get(
            reverse("api_v1:transaction-list"),
            {"search": "GROCERY"},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1


########################################################################
########################################################################
#
class TestTransactionAllocationAPI:
    """Tests for the /api/v1/allocations/ endpoint.

    The endpoint is read-only.  All allocation mutations (create,
    update, delete) must go through POST /api/v1/transactions/<id>/splits/.
    """

    ####################################################################
    #
    def test_list_requires_auth(self, api_client: APIClient) -> None:
        """
        GIVEN: an unauthenticated client
        WHEN:  GET /api/v1/allocations/
        THEN:  401 Unauthorized
        """
        response = api_client.get(reverse("api_v1:transactionallocation-list"))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    ####################################################################
    #
    def test_list_returns_own_allocations(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
        transaction_allocation_factory: Callable[..., TransactionAllocation],
    ) -> None:
        """
        GIVEN: two allocations owned by the authenticated user
        WHEN:  GET /api/v1/allocations/
        THEN:  both allocations are returned
        """
        account = bank_account_factory(owners=[user])
        tx = transaction_factory(bank_account=account)
        transaction_allocation_factory(
            transaction=tx, budget=account.unallocated_budget
        )
        transaction_allocation_factory(
            transaction=tx, budget=account.unallocated_budget
        )
        response = auth_client.get(reverse("api_v1:transactionallocation-list"))
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) >= 2

    ####################################################################
    #
    def test_retrieve_allocation(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
        transaction_allocation_factory: Callable[..., TransactionAllocation],
    ) -> None:
        """
        GIVEN: an existing allocation
        WHEN:  GET /api/v1/allocations/<id>/
        THEN:  200 OK with the allocation's data
        """
        account = bank_account_factory(owners=[user])
        tx = transaction_factory(bank_account=account)
        alloc = transaction_allocation_factory(
            transaction=tx, budget=account.unallocated_budget
        )
        response = auth_client.get(
            reverse(
                "api_v1:transactionallocation-detail",
                kwargs={"id": alloc.id},
            )
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == str(alloc.id)

    ####################################################################
    #
    @pytest.mark.parametrize(
        "method,use_detail",
        [
            ("post", False),
            ("put", True),
            ("patch", True),
            ("delete", True),
        ],
        ids=["post", "put", "patch", "delete"],
    )
    def test_mutation_methods_not_allowed(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
        transaction_allocation_factory: Callable[..., TransactionAllocation],
        method: str,
        use_detail: bool,
    ) -> None:
        """
        GIVEN: an existing allocation
        WHEN:  POST, PUT, PATCH, or DELETE is sent to the allocations endpoint
        THEN:  405 Method Not Allowed -- mutations go through /splits/
        """
        account = bank_account_factory(owners=[user])
        tx = transaction_factory(bank_account=account)
        alloc = transaction_allocation_factory(
            transaction=tx, budget=account.unallocated_budget
        )
        if use_detail:
            url = reverse(
                "api_v1:transactionallocation-detail",
                kwargs={"id": alloc.id},
            )
        else:
            url = reverse("api_v1:transactionallocation-list")
        response = getattr(auth_client, method)(url, {})
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


########################################################################
########################################################################
#
class TestTransactionSplitsAPI:
    """Tests for the POST /api/v1/transactions/<id>/splits/ endpoint."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "split_spec, expected_alloc_count, expected_balance_deltas",
        [
            # Single budget, full amount — no remainder.
            ({"A": "100.00"}, 1, {"A": -100}),
            # Two budgets, partial — remainder to unallocated.
            (
                {"A": "50.00", "B": "30.00"},
                3,
                {"A": -50, "B": -30},
            ),
            # Two budgets, full amount — no remainder.
            (
                {"A": "60.00", "B": "40.00"},
                2,
                {"A": -60, "B": -40},
            ),
            # Empty splits — everything back to unallocated.
            ({}, 1, {}),
        ],
        ids=[
            "single-full",
            "multi-with-remainder",
            "multi-exact",
            "empty-to-unallocated",
        ],
    )
    def test_splits_reconciliation(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
        transaction_allocation_factory: Callable[..., TransactionAllocation],
        budget_factory: Callable[..., Budget],
        split_spec: dict[str, str],
        expected_alloc_count: int,
        expected_balance_deltas: dict[str, int],
    ) -> None:
        """
        GIVEN: a -100 transaction with one unallocated allocation and
               two budgets (A, B) each starting at $500
        WHEN:  POST splits with the given split_spec
        THEN:  the expected number of allocations exist with correct
               amounts, and budget balances reflect the deltas
        """
        account = bank_account_factory(owners=[user])
        budgets = {
            "A": budget_factory(
                bank_account=account, balance=Money(500, "USD")
            ),
            "B": budget_factory(
                bank_account=account, balance=Money(500, "USD")
            ),
        }
        tx = transaction_factory(
            bank_account=account, amount=Money(-100, "USD")
        )
        unalloc = account.unallocated_budget
        assert unalloc is not None

        transaction_allocation_factory(
            transaction=tx,
            budget=unalloc,
            amount=Money(-100, "USD"),
        )

        unalloc_before = Budget.objects.get(id=unalloc.id).balance

        # Map symbolic keys ("A", "B") to real budget UUIDs.
        request_splits = {str(budgets[k].id): v for k, v in split_spec.items()}

        response = auth_client.post(
            reverse(
                "api_v1:transaction-splits",
                kwargs={"id": tx.id},
            ),
            {"splits": request_splits},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == expected_alloc_count

        # Verify allocation amounts.
        by_budget = {str(a["budget"]): a for a in response.data}
        for key, amount_str in split_spec.items():
            bid = str(budgets[key].id)
            assert Decimal(by_budget[bid]["amount"]) == Decimal(
                f"-{amount_str}"
            )

        # Verify remainder allocation if present.
        split_total = sum(Decimal(v) for v in split_spec.values())
        remainder = Decimal("100") - split_total
        unalloc_id = str(unalloc.id)
        if remainder > 0:
            assert Decimal(by_budget[unalloc_id]["amount"]) == -remainder

        # Verify budget balances.
        for key, delta in expected_balance_deltas.items():
            budgets[key].refresh_from_db()
            assert budgets[key].balance == Money(500 + delta, "USD")

        # Verify unallocated budget gained back what it lost.
        unalloc_after = Budget.objects.get(id=unalloc.id).balance
        expected_unalloc_gain = Decimal("100") - remainder
        assert unalloc_after == unalloc_before + Money(
            expected_unalloc_gain, "USD"
        )

        # Verify budget_balance snapshots: each returned allocation is the
        # only allocation for its budget in this test, so its budget_balance
        # must equal the budget's current balance.
        for alloc_data in response.data:
            budget_in_db = Budget.objects.get(id=alloc_data["budget"])
            assert (
                Decimal(alloc_data["budget_balance"])
                == budget_in_db.balance.amount
            ), (
                f"budget_balance snapshot mismatch for budget {alloc_data['budget']}: "
                f"response={alloc_data['budget_balance']} db={budget_in_db.balance.amount}"
            )

    ####################################################################
    #
    def test_splits_exceeding_transaction_rejected(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
        transaction_allocation_factory: Callable[..., TransactionAllocation],
        budget_factory: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: a -100 transaction
        WHEN:  POST splits totalling 150
        THEN:  400 Bad Request
        """
        account = bank_account_factory(owners=[user])
        budget = budget_factory(bank_account=account)
        tx = transaction_factory(
            bank_account=account, amount=Money(-100, "USD")
        )
        transaction_allocation_factory(
            transaction=tx,
            budget=account.unallocated_budget,
            amount=Money(-100, "USD"),
        )

        response = auth_client.post(
            reverse(
                "api_v1:transaction-splits",
                kwargs={"id": tx.id},
            ),
            {"splits": {str(budget.id): "150.00"}},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    ####################################################################
    #
    def test_resplit_updates_existing_allocations(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
        transaction_allocation_factory: Callable[..., TransactionAllocation],
        budget_factory: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: a -100 transaction split 60/40 across two budgets
        WHEN:  POST splits changing to 70/30
        THEN:  allocations are updated in place, budget balances
               reflect the change
        """
        account = bank_account_factory(owners=[user])
        budget_a = budget_factory(
            bank_account=account, balance=Money(500, "USD")
        )
        budget_b = budget_factory(
            bank_account=account, balance=Money(500, "USD")
        )
        tx = transaction_factory(
            bank_account=account, amount=Money(-100, "USD")
        )
        transaction_allocation_factory(
            transaction=tx,
            budget=budget_a,
            amount=Money(-60, "USD"),
        )
        transaction_allocation_factory(
            transaction=tx,
            budget=budget_b,
            amount=Money(-40, "USD"),
        )

        response = auth_client.post(
            reverse(
                "api_v1:transaction-splits",
                kwargs={"id": tx.id},
            ),
            {
                "splits": {
                    str(budget_a.id): "70.00",
                    str(budget_b.id): "30.00",
                }
            },
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 2

        budget_a.refresh_from_db()
        budget_b.refresh_from_db()
        assert budget_a.balance == Money(430, "USD")
        assert budget_b.balance == Money(470, "USD")

    ####################################################################
    #
    def test_unknown_budget_rejected(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
        transaction_allocation_factory: Callable[..., TransactionAllocation],
    ) -> None:
        """
        GIVEN: a transaction
        WHEN:  POST splits with a non-existent budget UUID
        THEN:  400 Bad Request
        """
        account = bank_account_factory(owners=[user])
        tx = transaction_factory(
            bank_account=account, amount=Money(-100, "USD")
        )
        transaction_allocation_factory(
            transaction=tx,
            budget=account.unallocated_budget,
            amount=Money(-100, "USD"),
        )

        response = auth_client.post(
            reverse(
                "api_v1:transaction-splits",
                kwargs={"id": tx.id},
            ),
            {"splits": {"00000000-0000-0000-0000-000000000000": "50.00"}},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    ####################################################################
    #
    @pytest.mark.parametrize(
        "same_owner",
        [True, False],
        ids=["same-owner-different-account", "different-owner"],
    )
    def test_cross_account_budget_rejected(
        self,
        auth_client: APIClient,
        user: User,
        user_factory: Callable[..., User],
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
        transaction_allocation_factory: Callable[..., TransactionAllocation],
        budget_factory: Callable[..., Budget],
        same_owner: bool,
    ) -> None:
        """
        GIVEN: a transaction on account A and a budget on account B
               (B owned by the same user or a different user)
        WHEN:  POST splits referencing the cross-account budget
        THEN:  400 Bad Request — budget must be in the same account
        """
        account_a = bank_account_factory(owners=[user])
        other_owner = [user] if same_owner else [user_factory()]
        account_b = bank_account_factory(owners=other_owner)
        budget_b = budget_factory(bank_account=account_b)
        tx = transaction_factory(
            bank_account=account_a, amount=Money(-100, "USD")
        )
        transaction_allocation_factory(
            transaction=tx,
            budget=account_a.unallocated_budget,
            amount=Money(-100, "USD"),
        )

        response = auth_client.post(
            reverse(
                "api_v1:transaction-splits",
                kwargs={"id": tx.id},
            ),
            {"splits": {str(budget_b.id): "50.00"}},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    ####################################################################
    #
    def test_splits_on_past_transaction_propagates_running_balances(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
        transaction_allocation_factory: Callable[..., TransactionAllocation],
        budget_factory: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: budget X with two allocations -- T1 (Jan 1, +$50) then
               T2 (Jan 15, +$30) -- so running balances are $50 and $80
        WHEN:  POST splits on T1 changes X's share from $50 to $20
        THEN:  T1's budget_balance snapshot becomes $20 and T2's
               downstream snapshot is propagated forward to $50
               (not left as a stale $80)
        """
        account = bank_account_factory(owners=[user])
        budget_x = budget_factory(bank_account=account, balance=Money(0, "USD"))

        t1 = transaction_factory(
            bank_account=account,
            amount=Money(50, "USD"),
            transaction_date=datetime(2024, 1, 1, tzinfo=UTC),
        )
        a1 = transaction_allocation_factory(
            transaction=t1, budget=budget_x, amount=Money(50, "USD")
        )

        t2 = transaction_factory(
            bank_account=account,
            amount=Money(30, "USD"),
            transaction_date=datetime(2024, 1, 15, tzinfo=UTC),
        )
        a2 = transaction_allocation_factory(
            transaction=t2, budget=budget_x, amount=Money(30, "USD")
        )

        # Sanity-check initial snapshots before the splits call.
        a1.refresh_from_db()
        a2.refresh_from_db()
        assert a1.budget_balance == Money(50, "USD")
        assert a2.budget_balance == Money(80, "USD")

        # Re-split T1: $20 to X, remainder to unallocated.
        response = auth_client.post(
            reverse("api_v1:transaction-splits", kwargs={"id": t1.id}),
            {"splits": {str(budget_x.id): "20.00"}},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

        # T1's allocation for X is updated; its snapshot reflects the new balance.
        a1.refresh_from_db()
        assert a1.amount == Money(20, "USD")
        assert a1.budget_balance == Money(20, "USD")

        # T2's snapshot must be propagated forward: 20 + 30 = 50.
        a2.refresh_from_db()
        assert a2.budget_balance == Money(50, "USD")

        # X's stored balance matches the final running total.
        budget_x.refresh_from_db()
        assert budget_x.balance == Money(50, "USD")


########################################################################
########################################################################
#
class TestRunningBalanceWithInternalTransactions:
    """Verify that budget_balance snapshots on TransactionAllocations
    account for InternalTransaction top-ups that occur between
    allocations chronologically.

    These tests mimic the backfill_budget command flow:

    1. Bank account starts with enough available_balance so
       the auto-created Unallocated budget has funds.
    2. Transactions are imported first -- each gets an allocation
       to Unallocated (the import pipeline's behavior).
    3. An InternalTransaction funds the target budget from
       Unallocated (the monthly top-up).
    4. The splits API moves each allocation from Unallocated
       to the target budget (the interactive allocation step).
    5. At a month boundary another InternalTransaction top-up
       occurs, then more splits follow.
    """

    ####################################################################
    #
    def test_backfill_flow_running_balances(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
        transaction_allocation_factory: Callable[..., TransactionAllocation],
        budget_factory: Callable[..., Budget],
        internal_transaction_factory: Callable[..., InternalTransaction],
    ) -> None:
        """
        GIVEN: a bank account with $5000 available, 10 imported
               transactions (each allocated to Unallocated),
               and a recurring budget with $0 starting balance
        WHEN:  the backfill flow runs --
                 1. fund budget to $500 from Unallocated
                 2. split 5 January transactions to the budget
                 3. fund budget back to $500 from Unallocated
                 4. split 5 February transactions to the budget
        THEN:  every allocation's budget_balance snapshot
               correctly reflects both the allocation amounts
               AND the InternalTransaction funding that
               preceded it

        Timeline (mimics backfill_budget month-by-month):
            Step 1:  InternalTransaction +$500 Unallocated -> budget
            Step 2:  Split T1..T5 (-$40 each) to budget
            Step 3:  InternalTransaction +$200 Unallocated -> budget
                     (top up from $300 back to $500)
            Step 4:  Split T6..T10 (-$40 each) to budget

        Expected running budget_balance after each split:
            T1:  500 - 40 = 460
            T2:  460 - 40 = 420
            T3:  420 - 40 = 380
            T4:  380 - 40 = 340
            T5:  340 - 40 = 300
            -- InternalTransaction +200 -> balance now 500 --
            T6:  500 - 40 = 460
            T7:  460 - 40 = 420
            T8:  420 - 40 = 380
            T9:  380 - 40 = 340
            T10: 340 - 40 = 300

        Final budget balance: $300
        """
        # -- Setup: bank account with $5000 so Unallocated starts
        # with enough to cover all funding and transactions. --
        account = bank_account_factory(
            owners=[user],
            available_balance=Money(5000, "USD"),
            posted_balance=Money(5000, "USD"),
        )
        unalloc = account.unallocated_budget
        assert unalloc is not None
        assert unalloc.balance == Money(5000, "USD")

        budget = budget_factory(bank_account=account, balance=Money(0, "USD"))

        # -- Step 0: Import all 10 transactions up front. --
        # Each gets an allocation to Unallocated, just like the
        # import pipeline does.
        imported_txs = []
        for i in range(10):
            tx = transaction_factory(
                bank_account=account,
                amount=Money(-40, "USD"),
                transaction_date=datetime(2024, 1, i + 1, tzinfo=UTC),
            )
            transaction_allocation_factory(
                transaction=tx,
                budget=unalloc,
                amount=Money(-40, "USD"),
            )
            imported_txs.append(tx)

        # -- Step 1: Initial funding -- top budget up to $500. --
        unalloc.refresh_from_db()
        internal_transaction_factory(
            bank_account=account,
            src_budget=unalloc,
            dst_budget=budget,
            amount=Money(500, "USD"),
            actor=user,
        )
        budget.refresh_from_db()
        assert budget.balance == Money(500, "USD")

        # -- Step 2: Split first 5 transactions to the budget,
        # checking the budget_balance snapshot after each one. --
        expected_first_batch = [460, 420, 380, 340, 300]
        for i, tx in enumerate(imported_txs[:5]):
            response = auth_client.post(
                reverse(
                    "api_v1:transaction-splits",
                    kwargs={"id": tx.id},
                ),
                {"splits": {str(budget.id): "40.00"}},
                format="json",
            )
            assert response.status_code == status.HTTP_200_OK

            # Validate the budget_balance on the allocation
            # returned by this split call.
            for alloc_data in response.data:
                if str(alloc_data["budget"]) == str(budget.id):
                    assert Decimal(alloc_data["budget_balance"]) == Decimal(
                        expected_first_batch[i]
                    ), (
                        f"Split {i + 1}: expected "
                        f"budget_balance="
                        f"{expected_first_batch[i]}, "
                        f"got {alloc_data['budget_balance']}"
                    )

        # After 5x -$40, budget should be at $300.
        budget.refresh_from_db()
        assert budget.balance == Money(300, "USD")

        # -- Step 3: Top-up -- fund back to $500. --
        unalloc.refresh_from_db()
        internal_transaction_factory(
            bank_account=account,
            src_budget=unalloc,
            dst_budget=budget,
            amount=Money(200, "USD"),
            actor=user,
        )
        budget.refresh_from_db()
        assert budget.balance == Money(500, "USD")

        # -- Step 4: Split remaining 5 transactions, again
        # checking each budget_balance snapshot immediately. --
        expected_second_batch = [460, 420, 380, 340, 300]
        for i, tx in enumerate(imported_txs[5:]):
            response = auth_client.post(
                reverse(
                    "api_v1:transaction-splits",
                    kwargs={"id": tx.id},
                ),
                {"splits": {str(budget.id): "40.00"}},
                format="json",
            )
            assert response.status_code == status.HTTP_200_OK

            for alloc_data in response.data:
                if str(alloc_data["budget"]) == str(budget.id):
                    assert Decimal(alloc_data["budget_balance"]) == Decimal(
                        expected_second_batch[i]
                    ), (
                        f"Split {i + 6}: expected "
                        f"budget_balance="
                        f"{expected_second_batch[i]}, "
                        f"got {alloc_data['budget_balance']}"
                    )

        # Final budget balance: 500 - 200 + 200 - 200 = 300.
        budget.refresh_from_db()
        assert budget.balance == Money(300, "USD")


########################################################################
########################################################################
#
class TestInternalTransactionAPI:
    """Tests for the /api/v1/internal-transactions/ endpoint."""

    ####################################################################
    #
    def test_create_internal_transaction(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
        budget_factory: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: an owned account with two budgets
        WHEN:  POST /api/v1/internal-transactions/ with amount, src, dst
        THEN:  the transfer is created and the actor is set to the user
        """
        account = bank_account_factory(owners=[user])
        src = budget_factory(bank_account=account, balance=Money(500, "USD"))
        dst = budget_factory(bank_account=account)
        response = auth_client.post(
            reverse("api_v1:internaltransaction-list"),
            {
                "bank_account": str(account.id),
                "amount": "100.00",
                "src_budget": str(src.id),
                "dst_budget": str(dst.id),
            },
        )
        assert response.status_code == status.HTTP_201_CREATED

        itx = InternalTransaction.objects.get(id=response.data["id"])
        assert itx.actor == user

    ####################################################################
    #
    def test_same_src_dst_rejected(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
        budget_factory: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: a single budget
        WHEN:  POST with src_budget == dst_budget
        THEN:  400 Bad Request is returned
        """
        account = bank_account_factory(owners=[user])
        budget = budget_factory(bank_account=account)
        response = auth_client.post(
            reverse("api_v1:internaltransaction-list"),
            {
                "bank_account": str(account.id),
                "amount": "50.00",
                "src_budget": str(budget.id),
                "dst_budget": str(budget.id),
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    ####################################################################
    #
    @pytest.mark.parametrize(
        ("which_cross", "same_owner"),
        [
            ("src", True),
            ("dst", True),
            ("src", False),
            ("dst", False),
        ],
        ids=[
            "src-same-owner",
            "dst-same-owner",
            "src-different-owner",
            "dst-different-owner",
        ],
    )
    def test_cross_account_budget_rejected(
        self,
        auth_client: APIClient,
        user: User,
        user_factory: Callable[..., User],
        bank_account_factory: Callable[..., BankAccount],
        budget_factory: Callable[..., Budget],
        which_cross: str,
        same_owner: bool,
    ) -> None:
        """
        GIVEN: two bank accounts (same or different owner) with
               budgets on each
        WHEN:  POST an internal transaction whose src or dst budget
               belongs to a different account than bank_account
        THEN:  400 Bad Request
        """
        account = bank_account_factory(owners=[user])
        other_owner = [user] if same_owner else [user_factory()]
        other_account = bank_account_factory(owners=other_owner)

        budget_here = budget_factory(bank_account=account)
        budget_there = budget_factory(bank_account=other_account)

        if which_cross == "src":
            src, dst = budget_there, budget_here
        else:
            src, dst = budget_here, budget_there

        response = auth_client.post(
            reverse("api_v1:internaltransaction-list"),
            {
                "bank_account": str(account.id),
                "amount": "50.00",
                "src_budget": str(src.id),
                "dst_budget": str(dst.id),
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    ####################################################################
    #
    @pytest.mark.parametrize("method", ["patch", "delete"])
    def test_update_and_delete_not_allowed(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
        budget_factory: Callable[..., Budget],
        internal_transaction_factory: Callable[..., InternalTransaction],
        method: str,
    ) -> None:
        """
        GIVEN: an existing internal transaction
        WHEN:  PATCH or DELETE /api/v1/internal-transactions/<uuid>/
        THEN:  405 Method Not Allowed is returned
        """
        account = bank_account_factory(owners=[user])
        src = budget_factory(bank_account=account, balance=Money(500, "USD"))
        dst = budget_factory(bank_account=account)
        itx = internal_transaction_factory(
            bank_account=account,
            src_budget=src,
            dst_budget=dst,
            actor=user,
        )
        url = reverse(
            "api_v1:internaltransaction-detail",
            kwargs={"id": itx.id},
        )
        response = getattr(auth_client, method)(url)
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


########################################################################
########################################################################
#
class TestPermissions:
    """Tests for ownership-based access control across all endpoints.

    The AccountOwnerQuerySetMixin has three code paths based on
    model type: BankAccount (owners=user), Budget/Transaction
    (bank_account__owners=user), and TransactionAllocation
    (transaction__bank_account__owners=user).  Each is tested here.

    NOTE: The parametrized factory_cls values are factory classes called
    directly because pytest_factoryboy fixtures cannot be used inside
    parametrize. This is the one place where direct factory calls are
    acceptable.
    """

    ####################################################################
    #
    @pytest.mark.parametrize(
        "factory_cls, detail_url_name",
        [
            (BankAccountFactory, "api_v1:bankaccount-detail"),
            (BudgetFactory, "api_v1:budget-detail"),
            (TransactionFactory, "api_v1:transaction-detail"),
        ],
        ids=["account", "budget", "transaction"],
    )
    @pytest.mark.parametrize(
        "is_staff, is_superuser",
        [
            (False, False),
            (True, True),
        ],
        ids=["regular", "staff-superuser"],
    )
    def test_cannot_retrieve_other_users_object(
        self,
        user: User,
        is_staff: bool,
        is_superuser: bool,
        factory_cls: type,
        detail_url_name: str,
        bank_account_factory: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: an object belonging to another user's account
        WHEN:  GET /api/v1/<resource>/<uuid>/
        THEN:  404 Not Found -- ownership filtering is not bypassed by
               staff or superuser privilege
        """
        user.is_staff = is_staff
        user.is_superuser = is_superuser
        user.save()

        client = APIClient()
        client.force_authenticate(user=user)

        other_account = bank_account_factory()

        if factory_cls is BankAccountFactory:
            obj = other_account
        else:
            obj = factory_cls(bank_account=other_account)

        response = client.get(
            reverse(detail_url_name, kwargs={"id": obj.id}),
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
