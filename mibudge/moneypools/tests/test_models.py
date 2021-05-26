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
from django.contrib.auth import get_user_model

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
def test_bank_account_factory(bank_account_factory):
    bank_account = bank_account_factory()
    assert isinstance(bank_account, BankAccount)
