#!/usr/bin/env python
#
"""Test that money inputs take their bank account's currency."""

# system imports
from collections.abc import Callable
from decimal import Decimal
from typing import NamedTuple

# 3rd party imports
import pytest
import pytest_check as check
from django.db.models import Model
from django.urls import reverse
from djmoney.contrib.django_rest_framework import MoneyField as DRFMoneyField
from djmoney.money import Money
from faker import Faker
from rest_framework import serializers as drf_serializers
from rest_framework.test import APIClient

# Project imports
from moneypools.api.v1 import serializers
from moneypools.api.v1.serializers.money import BankAccountCurrencyMixin
from moneypools.models import (
    Bank,
    BankAccount,
    Budget,
    InternalTransaction,
    Transaction,
)
from users.models import User

from .payloads import budget_payload, transaction_payload, transfer_payload

pytestmark = pytest.mark.django_db

MISMATCH = "Must be the bank account's currency, 'EUR'."


########################################################################
########################################################################
#
class CreateRequest(NamedTuple):
    """A create request carrying one money amount."""

    url: str
    payload: dict
    money_field: str
    model: type[Model]


####################################################################
#
@pytest.fixture
def account(
    bank_factory: Callable[..., Bank],
    bank_account_factory: Callable[..., BankAccount],
    user: User,
) -> BankAccount:
    """A EUR bank account, at a EUR bank, owned by `user`.

    On a USD bank account the server default and the bank account's
    currency are the same, so these tests would pass whatever currency
    was applied.
    """
    bank = bank_factory(default_currency="EUR")
    return bank_account_factory(bank=bank, currency="EUR", owners=[user])


####################################################################
#
@pytest.fixture
def bank_account_create(account: BankAccount, faker: Faker) -> CreateRequest:
    """A new bank account at `account`'s (EUR) bank, with an opening balance."""
    return CreateRequest(
        reverse("api_v1:bankaccount-list"),
        {
            "name": faker.company(),
            "bank": str(account.bank.id),
            "account_type": "C",
            "account_number": faker.iban(),
            "posted_balance": "100.00",
            "available_balance": "100.00",
        },
        "posted_balance",
        BankAccount,
    )


####################################################################
#
@pytest.fixture
def budget_create(account: BankAccount, faker: Faker) -> CreateRequest:
    """A fixed-amount Goal budget on `account`."""
    return CreateRequest(
        reverse("api_v1:budget-list"),
        budget_payload(
            account,
            name=faker.word(),
            funding_type="F",
            funding_amount="10.00",
        ),
        "funding_amount",
        Budget,
    )


####################################################################
#
@pytest.fixture
def transaction_create(account: BankAccount, faker: Faker) -> CreateRequest:
    """A purchase on `account`."""
    return CreateRequest(
        reverse("api_v1:transaction-list"),
        transaction_payload(account, raw_description=faker.company().upper()),
        "amount",
        Transaction,
    )


####################################################################
#
@pytest.fixture
def transfer_create(
    account: BankAccount, unallocated: Budget, goal: Budget
) -> CreateRequest:
    """A transfer from Unallocated to `goal` on `account`."""
    return CreateRequest(
        reverse("api_v1:internaltransaction-list"),
        transfer_payload(account, unallocated, goal),
        "amount",
        InternalTransaction,
    )


####################################################################
#
@pytest.fixture
def create_request(request: pytest.FixtureRequest) -> CreateRequest:
    """The create-request fixture the test's parameter names."""
    return request.getfixturevalue(request.param)


# The account's own `currency` default is `test_new_account_takes_bank_
# currency`; the other creates default only their money field.
#
DEFAULTED_CREATES = pytest.mark.parametrize(
    "create_request",
    ["budget_create", "transaction_create", "transfer_create"],
    indirect=True,
)
ALL_CREATES = pytest.mark.parametrize(
    "create_request",
    [
        "bank_account_create",
        "budget_create",
        "transaction_create",
        "transfer_create",
    ],
    indirect=True,
)


####################################################################
#
@pytest.fixture
def pending_purchase(
    account: BankAccount, transaction_factory: Callable[..., Transaction]
) -> Transaction:
    """A pending EUR purchase on `account`."""
    return transaction_factory(
        bank_account=account,
        amount=Money(Decimal("-20.00"), "EUR"),
        pending=True,
    )


####################################################################
#
@pytest.fixture
def scrape_payload(faker: Faker) -> dict:
    """A two-row, all-posted scrape with no currencies given."""
    return {
        "scraped_at": "2026-09-29T08:00:00Z",
        "ending_balance": "93.60",
        "transactions": [
            {
                "is_pending": False,
                "posted_date": f"2026-09-2{day}T00:00:00Z",
                "raw_description": f"{faker.company().upper()} 09/2{day}",
                "amount": "-3.20",
            }
            for day in (8, 7)
        ],
    }


########################################################################
########################################################################
#
class TestMoneyCurrency:
    """Money inputs resolve to the bank account's currency."""

    ####################################################################
    #
    @DEFAULTED_CREATES
    def test_omitted_currency_is_the_bank_accounts(
        self, auth_client: APIClient, create_request: CreateRequest
    ) -> None:
        """
        GIVEN: a EUR bank account
        WHEN:  a money amount is sent without its `<field>_currency`
        THEN:  it is stored in EUR
        """
        url, payload, field, _ = create_request

        response = auth_client.post(url, payload, format="json")

        assert response.status_code == 201, response.data
        assert response.data[f"{field}_currency"] == "EUR"

    ####################################################################
    #
    @ALL_CREATES
    def test_other_currency_refused(
        self, auth_client: APIClient, create_request: CreateRequest
    ) -> None:
        """
        GIVEN: a EUR bank account
        WHEN:  a money amount is sent with `<field>_currency` USD
        THEN:  400 on `<field>_currency`, and nothing is created
        """
        url, payload, field, model = create_request
        before = model.objects.count()  # type: ignore[attr-defined]

        response = auth_client.post(
            url, {**payload, f"{field}_currency": "USD"}, format="json"
        )

        assert response.status_code == 400
        check.equal(
            response.data.get(f"{field}_currency"), [MISMATCH], "on the field"
        )
        check.equal(
            model.objects.count(),  # type: ignore[attr-defined]
            before,
            "nothing is created",
        )

    ####################################################################
    #
    def test_new_account_takes_bank_currency(
        self, auth_client: APIClient, bank_account_create: CreateRequest
    ) -> None:
        """
        GIVEN: a EUR bank
        WHEN:  a bank account is created there without `currency`
        THEN:  the bank account and its balances are EUR
        """
        url, payload, _, _ = bank_account_create

        response = auth_client.post(url, payload, format="json")

        assert response.status_code == 201, response.data
        check.equal(response.data["currency"], "EUR", "the bank's currency")
        check.equal(
            response.data["posted_balance_currency"], "EUR", "balances too"
        )

    ####################################################################
    #
    def test_resolve_pending_other_currency_refused(
        self, auth_client: APIClient, pending_purchase: Transaction
    ) -> None:
        """
        GIVEN: a pending EUR purchase
        WHEN:  it is resolved with a final amount in USD
        THEN:  400 on `amount_currency`, and it stays pending
        """
        response = auth_client.post(
            reverse(
                "api_v1:transaction-resolve-pending",
                kwargs={"id": pending_purchase.id},
            ),
            {
                "posted_date": "2026-09-29T12:00:00Z",
                "amount": "-21.50",
                "amount_currency": "USD",
            },
            format="json",
        )

        assert response.status_code == 400
        check.equal(response.data.get("amount_currency"), [MISMATCH], "on it")
        pending_purchase.refresh_from_db()
        check.is_true(pending_purchase.pending, "still pending")

    ####################################################################
    #
    def test_sync_scrape_without_currencies_syncs_in_eur(
        self,
        auth_client: APIClient,
        account: BankAccount,
        scrape_payload: dict,
    ) -> None:
        """
        GIVEN: a EUR bank account and a scrape that names no currencies
        WHEN:  it is synced
        THEN:  both rows are inserted, in EUR
        """
        response = auth_client.post(
            reverse(
                "api_v1:bankaccount-sync-scrape", kwargs={"id": account.id}
            ),
            scrape_payload,
            format="json",
        )

        assert response.status_code == 200, response.data
        currencies = {
            str(tx.amount.currency)
            for tx in Transaction.objects.filter(bank_account=account)
        }
        check.equal(response.data["inserted_posted"], 2, "both rows")
        check.equal(currencies, {"EUR"}, "in EUR")

    ####################################################################
    #
    def test_sync_scrape_row_currency_refused(
        self,
        auth_client: APIClient,
        account: BankAccount,
        scrape_payload: dict,
    ) -> None:
        """
        GIVEN: a EUR bank account and a scrape whose second row is USD
        WHEN:  it is synced
        THEN:  400, with the error on that row's `amount_currency`
        """
        scrape_payload["transactions"][1]["amount_currency"] = "USD"

        response = auth_client.post(
            reverse(
                "api_v1:bankaccount-sync-scrape", kwargs={"id": account.id}
            ),
            scrape_payload,
            format="json",
        )

        assert response.status_code == 400
        assert response.data == {
            "transactions": [{}, {"amount_currency": [MISMATCH]}]
        }


########################################################################
########################################################################
#
class TestMoneySerializersResolveCurrency:
    """Every money input goes through `BankAccountCurrencyMixin`."""

    ####################################################################
    #
    def test_money_input_serializers_use_mixin(self) -> None:
        """
        GIVEN: the moneypools v1 serializers
        WHEN:  one has a writable money field
        THEN:  it includes `BankAccountCurrencyMixin` (the schema documents
               the currency rule for every writable money field), unless
               it is listed here with the reason it does not need it
        """
        # Not a request body of their own: the scrape's rows are resolved
        # by `ScrapeSyncSerializer`, and allocations have no writable
        # endpoint (they change through the transaction `splits` action).
        #
        exempt = {
            serializers.ScrapeSyncTransactionSerializer,
            serializers.TransactionAllocationSerializer,
        }
        with_money = [
            cls
            for name in serializers.__all__
            if isinstance(cls := getattr(serializers, name), type)
            and issubclass(cls, drf_serializers.Serializer)
            and any(
                isinstance(f, DRFMoneyField) and not f.read_only
                for f in cls().fields.values()
            )
        ]
        assert with_money

        missing = [
            cls.__name__
            for cls in with_money
            if cls not in exempt
            and not issubclass(cls, BankAccountCurrencyMixin)
        ]

        assert missing == []
