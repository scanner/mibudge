#!/usr/bin/env python
#
"""Test that money inputs take their bank account's currency."""

# system imports
from collections.abc import Callable
from decimal import Decimal
from typing import Any

# 3rd party imports
import pytest
import pytest_check as check
from django.urls import reverse
from djmoney.contrib.django_rest_framework import MoneyField as DRFMoneyField
from djmoney.money import Money
from rest_framework import serializers as drf_serializers
from rest_framework.test import APIClient

# Project imports
from moneypools.api.v1 import serializers
from moneypools.api.v1.serializers.money import BankAccountCurrencyMixin
from moneypools.models import Bank, BankAccount, Budget, Transaction
from users.models import User

pytestmark = pytest.mark.django_db

MISMATCH = "Must be the bank account's currency, 'EUR'."


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
def bank_account_create(account: BankAccount, *_: Any) -> tuple[str, dict]:
    """A new bank account at `account`'s (EUR) bank, with an opening balance."""
    return reverse("api_v1:bankaccount-list"), {
        "name": "Giro",
        "bank": str(account.bank.id),
        "account_type": "C",
        "account_number": "DE89370400440532013000",
        "posted_balance": "100.00",
        "available_balance": "100.00",
    }


def budget_create(account: BankAccount, *_: Any) -> tuple[str, dict]:
    """A fixed-amount Goal budget on `account`."""
    return reverse("api_v1:budget-list"), {
        "name": "Holiday",
        "bank_account": str(account.id),
        "budget_type": "G",
        "funding_type": "F",
        "target_balance": "500.00",
        "funding_amount": "50.00",
    }


def transaction_create(account: BankAccount, *_: Any) -> tuple[str, dict]:
    """A purchase on `account`."""
    return reverse("api_v1:transaction-list"), {
        "bank_account": str(account.id),
        "amount": "-12.34",
        "posted_date": "2026-09-28T12:00:00Z",
        "transaction_type": "signature_purchase",
        "raw_description": "BAECKEREI 09/28 PURCHASE",
    }


def transfer_create(
    account: BankAccount, unallocated: Budget, goal: Budget
) -> tuple[str, dict]:
    """A transfer from Unallocated to `goal` on `account`."""
    return reverse("api_v1:internaltransaction-list"), {
        "bank_account": str(account.id),
        "amount": "5.00",
        "src_budget": str(unallocated.id),
        "dst_budget": str(goal.id),
    }


CREATES = pytest.mark.parametrize(
    "build,field",
    [
        (bank_account_create, "posted_balance"),
        (budget_create, "funding_amount"),
        (transaction_create, "amount"),
        (transfer_create, "amount"),
    ],
    ids=["bank-account", "budget", "transaction", "transfer"],
)


########################################################################
########################################################################
#
class TestMoneyCurrency:
    """Money inputs resolve to the bank account's currency."""

    ####################################################################
    #
    @CREATES
    def test_omitted_currency_is_the_accounts(
        self,
        auth_client: APIClient,
        account: BankAccount,
        unallocated: Budget,
        goal: Budget,
        build: Callable[..., tuple[str, dict]],
        field: str,
    ) -> None:
        """
        GIVEN: a EUR bank account
        WHEN:  a money amount is sent without its `<field>_currency`
        THEN:  it is stored in EUR
        """
        url, payload = build(account, unallocated, goal)

        response = auth_client.post(url, payload, format="json")

        assert response.status_code == 201, response.data
        assert response.data[f"{field}_currency"] == "EUR"

    ####################################################################
    #
    @CREATES
    def test_other_currency_refused(
        self,
        auth_client: APIClient,
        account: BankAccount,
        unallocated: Budget,
        goal: Budget,
        build: Callable[..., tuple[str, dict]],
        field: str,
    ) -> None:
        """
        GIVEN: a EUR bank account
        WHEN:  a money amount is sent with `<field>_currency` USD
        THEN:  400 on `<field>_currency`, and nothing is created
        """
        url, payload = build(account, unallocated, goal)
        payload[f"{field}_currency"] = "USD"

        response = auth_client.post(url, payload, format="json")

        check.equal(response.status_code, 400, "refused")
        check.equal(
            response.data.get(f"{field}_currency"), [MISMATCH], "on the field"
        )

    ####################################################################
    #
    def test_new_account_takes_bank_currency(
        self, auth_client: APIClient, account: BankAccount
    ) -> None:
        """
        GIVEN: a EUR bank
        WHEN:  a bank account is created there without `currency`
        THEN:  the bank account and its balances are EUR
        """
        url, payload = bank_account_create(account)

        response = auth_client.post(url, payload, format="json")

        assert response.status_code == 201, response.data
        check.equal(response.data["currency"], "EUR", "the bank's currency")
        check.equal(
            response.data["available_balance_currency"], "EUR", "balances too"
        )

    ####################################################################
    #
    def test_resolve_pending_other_currency_refused(
        self,
        auth_client: APIClient,
        account: BankAccount,
        transaction_factory: Callable[..., Transaction],
    ) -> None:
        """
        GIVEN: a pending EUR purchase
        WHEN:  it is resolved with a final amount in USD
        THEN:  400 on `amount_currency`, and it stays pending
        """
        tx = transaction_factory(
            bank_account=account,
            amount=Money(Decimal("-20.00"), "EUR"),
            pending=True,
        )

        response = auth_client.post(
            reverse("api_v1:transaction-resolve-pending", kwargs={"id": tx.id}),
            {
                "posted_date": "2026-09-29T12:00:00Z",
                "amount": "-21.50",
                "amount_currency": "USD",
            },
            format="json",
        )

        check.equal(response.status_code, 400, "refused")
        check.equal(response.data.get("amount_currency"), [MISMATCH], "on it")
        tx.refresh_from_db()
        check.is_true(tx.pending, "still pending")

    ####################################################################
    #
    @pytest.mark.parametrize(
        "currencies,status,errors",
        [
            ({}, 200, None),
            (
                {"amount_currency": "USD"},
                400,
                {"transactions": [{}, {"amount_currency": [MISMATCH]}]},
            ),
        ],
        ids=["omitted", "other-in-one-row"],
    )
    def test_sync_scrape_currencies(
        self,
        auth_client: APIClient,
        account: BankAccount,
        currencies: dict,
        status: int,
        errors: dict | None,
    ) -> None:
        """
        GIVEN: a EUR bank account and a two-row scrape
        WHEN:  it is synced with no currencies, or with USD on one row
        THEN:  without currencies it syncs in EUR; with USD the error
               names that row's `amount_currency`
        """
        rows = [
            {
                "is_pending": False,
                "posted_date": f"2026-09-2{day}T00:00:00Z",
                "raw_description": f"BAECKEREI 09/2{day} PURCHASE",
                "amount": "-3.20",
            }
            for day in (8, 7)
        ]
        rows[1].update(currencies)

        response = auth_client.post(
            reverse(
                "api_v1:bankaccount-sync-scrape", kwargs={"id": account.id}
            ),
            {
                "scraped_at": "2026-09-29T08:00:00Z",
                "ending_balance": "93.60",
                "transactions": rows,
            },
            format="json",
        )

        assert response.status_code == status, response.data
        if errors is not None:
            assert response.data == errors


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
