"""Tests for moneypools factories -- verifies each factory produces the correct model type."""

# system imports
#
from collections.abc import Callable

# 3rd party imports
#
import pytest
from moneyed import USD, Money

# app imports
#
from moneypools.models import (
    Bank,
    BankAccount,
    Budget,
    InternalTransaction,
    Transaction,
)

pytestmark = pytest.mark.django_db


########################################################################
########################################################################
#
class TestFactories:
    """Smoke tests confirming each factory produces a correctly typed instance."""

    ####################################################################
    #
    def test_bank_factory(self, bank_factory: Callable[..., Bank]) -> None:
        """
        GIVEN: the bank_factory fixture
        WHEN:  called with no arguments
        THEN:  a Bank instance is returned
        """
        bank = bank_factory()
        assert isinstance(bank, Bank)

    ####################################################################
    #
    def test_bank_account_factory(
        self,
        bank_account_factory: Callable[..., BankAccount],
        bank_factory: Callable[..., Bank],
    ) -> None:
        """
        GIVEN: bank_account_factory and bank_factory fixtures
        WHEN:  bank accounts are created with default args, an explicit bank,
               and explicit field values
        THEN:  each account is a BankAccount instance, bank association and
               field values reflect what was passed to the factory
        """
        bank_account = bank_account_factory()
        old_bank = bank_account.bank
        assert isinstance(bank_account, BankAccount)

        bank = bank_factory(name="foo")
        assert old_bank.id != bank.id

        bank_account = bank_account_factory(bank=bank)
        assert bank == bank_account.bank
        assert old_bank != bank_account.bank

        bank_account = bank_account_factory(
            account_number="12345", posted_balance=12345.00
        )
        assert bank_account.account_number == "12345"
        assert bank_account.posted_balance == Money(12345.00, USD)

    ####################################################################
    #
    def test_budget_factory(
        self, budget_factory: Callable[..., Budget]
    ) -> None:
        """
        GIVEN: the budget_factory fixture
        WHEN:  called with no arguments
        THEN:  a Budget instance is returned
        """
        budget = budget_factory()
        assert isinstance(budget, Budget)

    ####################################################################
    #
    def test_transaction_factory(
        self, transaction_factory: Callable[..., Transaction]
    ) -> None:
        """
        GIVEN: the transaction_factory fixture
        WHEN:  called with no arguments
        THEN:  a Transaction instance is returned
        """
        transaction = transaction_factory()
        assert isinstance(transaction, Transaction)

    ####################################################################
    #
    def test_internal_transaction_factory(
        self, internal_transaction_factory: Callable[..., InternalTransaction]
    ) -> None:
        """
        GIVEN: the internal_transaction_factory fixture
        WHEN:  called with no arguments
        THEN:  an InternalTransaction instance is returned
        """
        internal_transaction = internal_transaction_factory()
        assert isinstance(internal_transaction, InternalTransaction)
