#!/usr/bin/env python
#
# File: $Id$
#
"""
Tests for the MoneyPools models and their somewhat complicated
business logic.
"""

# system imports
#

# 3rd party module imports
#
import pytest
from moneyed import Money, USD

# Application imports
#
# XXX when moneypools is moved into a separate app this needs to be
#     unbound also
#
from mibudge.users.tests.factories import UserFactory
from ..models import Bank, BankAccount, Budget, Transaction, InternalTransaction

pytestmark = pytest.mark.django_db


####################################################################
#
def test_bank_factory(bank_factory):
    bank = bank_factory()
    assert isinstance(bank, Bank)


####################################################################
#
def test_bank_account_factory(bank_account_factory, bank_factory):
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
