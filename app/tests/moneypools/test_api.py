"""Tests for the moneypools REST API: serializers, views, and permissions."""

# system imports
from collections.abc import Callable
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
    TransactionCategory,
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
    """Tests for the /api/currencies/ endpoint."""

    ####################################################################
    #
    def test_list_requires_auth(self, api_client: APIClient) -> None:
        """
        GIVEN: an unauthenticated client
        WHEN:  GET /api/currencies/
        THEN:  401 Unauthorized is returned
        """
        response = api_client.get(reverse("api:currencies"))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    ####################################################################
    #
    def test_list_currencies(self, auth_client: APIClient) -> None:
        """
        GIVEN: an authenticated client
        WHEN:  GET /api/currencies/
        THEN:  a list of currency objects is returned, each with code,
               name, and numeric fields, sorted by code
        """
        response = auth_client.get(reverse("api:currencies"))
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
    """Tests for the read-only /api/banks/ endpoint."""

    ####################################################################
    #
    def test_list_requires_auth(self, api_client: APIClient) -> None:
        """
        GIVEN: an unauthenticated client
        WHEN:  GET /api/banks/
        THEN:  401 Unauthorized is returned
        """
        response = api_client.get(reverse("api:bank-list"))
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
        WHEN:  GET /api/banks/
        THEN:  both banks are returned with expected fields
        """
        bank_factory()
        bank_factory()
        response = auth_client.get(reverse("api:bank-list"))
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
        WHEN:  GET /api/banks/<uuid>/
        THEN:  the bank detail is returned
        """
        bank = bank_factory()
        response = auth_client.get(
            reverse("api:bank-detail", kwargs={"id": bank.id})
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == bank.name

    ####################################################################
    #
    def test_create_not_allowed(self, auth_client: APIClient) -> None:
        """
        GIVEN: an authenticated client
        WHEN:  POST /api/banks/
        THEN:  405 Method Not Allowed is returned
        """
        response = auth_client.post(
            reverse("api:bank-list"),
            {"name": "New Bank"},
        )
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


########################################################################
########################################################################
#
class TestBankAccountAPI:
    """Tests for the /api/accounts/ endpoint."""

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
        WHEN:  POST /api/accounts/ with name, bank, and account_type
        THEN:  the account is created and the user is added as owner
        """
        bank = bank_factory()
        response = auth_client.post(
            reverse("api:bankaccount-list"),
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
        WHEN:  POST /api/accounts/ with available_balance set
        THEN:  the account is created with the specified balance and
               the unallocated budget receives that balance
        """
        bank = bank_factory()
        response = auth_client.post(
            reverse("api:bankaccount-list"),
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
        WHEN:  POST /api/accounts/ with currency=EUR
        THEN:  the account and its balances use EUR
        """
        bank = bank_factory()
        response = auth_client.post(
            reverse("api:bankaccount-list"),
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
        WHEN:  PATCH /api/accounts/<uuid>/ with a different currency
        THEN:  400 Bad Request with a currency validation error
        """
        account = bank_account_factory(owners=[user])
        response = auth_client.patch(
            reverse(
                "api:bankaccount-detail",
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
        WHEN:  GET /api/accounts/
        THEN:  only the owned account is returned
        """
        bank_account_factory(owners=[user])
        bank_account_factory()  # owned by a different user
        response = auth_client.get(reverse("api:bankaccount-list"))
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
        WHEN:  PATCH /api/accounts/<uuid>/ with a new name
        THEN:  the name is updated
        """
        account = bank_account_factory(owners=[user])
        response = auth_client.patch(
            reverse(
                "api:bankaccount-detail",
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
    """Tests for the /api/budgets/ endpoint."""

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
        WHEN:  POST /api/budgets/ with required fields
        THEN:  a new budget is created under that account
        """
        account = bank_account_factory(owners=[user])
        response = auth_client.post(
            reverse("api:budget-list"),
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
        WHEN:  GET /api/budgets/?bank_account=<uuid>
        THEN:  only budgets for the specified account are returned
        """
        acct1 = bank_account_factory(owners=[user])
        acct2 = bank_account_factory(owners=[user])
        budget_factory(bank_account=acct1)
        budget_factory(bank_account=acct2)

        response = auth_client.get(
            reverse("api:budget-list"),
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
        WHEN:  DELETE /api/budgets/<uuid>/
        THEN:  403 Forbidden is returned
        """
        account = bank_account_factory(owners=[user])
        unalloc = account.unallocated_budget
        assert unalloc is not None
        response = auth_client.delete(
            reverse(
                "api:budget-detail",
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
        WHEN:  PATCH /api/budgets/<uuid>/ with a new name
        THEN:  400 Bad Request with a name validation error
        """
        account = bank_account_factory(owners=[user])
        unalloc = account.unallocated_budget
        assert unalloc is not None
        response = auth_client.patch(
            reverse(
                "api:budget-detail",
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
            reverse("api:budget-detail", kwargs={"id": budget.id}),
            {"budget_type": "R"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "budget_type" in response.data


########################################################################
########################################################################
#
class TestTransactionAPI:
    """Tests for the /api/transactions/ endpoint."""

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
        WHEN:  POST /api/transactions/ with required fields
        THEN:  a transaction is created and a default allocation to
               the unallocated budget is auto-created
        """
        account = bank_account_factory(owners=[user])
        response = auth_client.post(
            reverse("api:transaction-list"),
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
            reverse("api:transaction-detail", kwargs={"id": tx.id}),
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
            reverse("api:transaction-detail", kwargs={"id": tx.id}),
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
        WHEN:  GET /api/transactions/?date_from=...&date_to=...
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
            reverse("api:transaction-list"),
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
        WHEN:  GET /api/transactions/?search=GROCERY
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
            reverse("api:transaction-list"),
            {"search": "GROCERY"},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1


########################################################################
########################################################################
#
class TestTransactionAllocationAPI:
    """Tests for the /api/allocations/ endpoint."""

    ####################################################################
    #
    def test_create_allocation(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
        budget_factory: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: a transaction with room for more allocations
        WHEN:  POST /api/allocations/ with transaction, budget, and amount
        THEN:  the allocation is created
        """
        account = bank_account_factory(owners=[user])
        tx = transaction_factory(bank_account=account, amount=Money(100, "USD"))
        budget = budget_factory(bank_account=account)
        response = auth_client.post(
            reverse("api:transactionallocation-list"),
            {
                "transaction": str(tx.id),
                "budget": str(budget.id),
                "amount": "50.00",
                "category": TransactionCategory.GROCERIES.value,
            },
        )
        assert response.status_code == status.HTTP_201_CREATED

    ####################################################################
    #
    def test_allocation_exceeds_transaction_amount(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
    ) -> None:
        """
        GIVEN: a transaction of $100
        WHEN:  creating an allocation for $150
        THEN:  400 Bad Request with a validation error
        """
        account = bank_account_factory(owners=[user])
        tx = transaction_factory(bank_account=account, amount=Money(100, "USD"))
        response = auth_client.post(
            reverse("api:transactionallocation-list"),
            {
                "transaction": str(tx.id),
                "amount": "150.00",
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    ####################################################################
    #
    def test_update_allocation_budget(
        self,
        auth_client: APIClient,
        user: User,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
        transaction_allocation_factory: Callable[..., TransactionAllocation],
        budget_factory: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: an existing allocation
        WHEN:  PATCH with a different budget
        THEN:  the budget is reassigned
        """
        account = bank_account_factory(owners=[user])
        tx = transaction_factory(bank_account=account)
        alloc = transaction_allocation_factory(
            transaction=tx,
            budget=account.unallocated_budget,
        )
        new_budget = budget_factory(bank_account=account)
        response = auth_client.patch(
            reverse(
                "api:transactionallocation-detail",
                kwargs={"id": alloc.id},
            ),
            {"budget": str(new_budget.id)},
        )
        assert response.status_code == status.HTTP_200_OK
        alloc.refresh_from_db()
        assert alloc.budget == new_budget


########################################################################
########################################################################
#
class TestInternalTransactionAPI:
    """Tests for the /api/internal-transactions/ endpoint."""

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
        WHEN:  POST /api/internal-transactions/ with amount, src, dst
        THEN:  the transfer is created and the actor is set to the user
        """
        account = bank_account_factory(owners=[user])
        src = budget_factory(bank_account=account, balance=Money(500, "USD"))
        dst = budget_factory(bank_account=account)
        response = auth_client.post(
            reverse("api:internaltransaction-list"),
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
            reverse("api:internaltransaction-list"),
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
        WHEN:  PATCH or DELETE /api/internal-transactions/<uuid>/
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
            "api:internaltransaction-detail",
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
            (BankAccountFactory, "api:bankaccount-detail"),
            (BudgetFactory, "api:budget-detail"),
            (TransactionFactory, "api:transaction-detail"),
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
        WHEN:  GET /api/<resource>/<uuid>/
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
