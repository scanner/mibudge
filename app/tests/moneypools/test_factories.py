# system imports
#

# 3rd party module imports
#
import pytest
from moneyed import USD, Money

# Application imports
#
from moneypools.models import (
    Bank,
    BankAccount,
    Budget,
    InternalTransaction,
    Transaction,
)

pytestmark = pytest.mark.django_db


####################################################################
#
def test_bank_factory(bank_factory):
    bank = bank_factory()
    assert isinstance(bank, Bank)


####################################################################
#
def test_bank_account_factory(bank_account_factory, bank_factory):
    # Make sure that we can make bank accounts that belong to
    # different banks and that setting attributes via kwargs does the
    # right thing.
    #
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
def test_budget_factory(budget_factory):
    budget = budget_factory()
    assert isinstance(budget, Budget)


####################################################################
#
def test_transaction_factory(transaction_factory):
    transaction = transaction_factory()
    assert isinstance(transaction, Transaction)


####################################################################
#
def test_internal_transaction_factory(internal_transaction_factory):
    internal_transaction = internal_transaction_factory()
    assert isinstance(internal_transaction, InternalTransaction)
