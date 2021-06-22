# system imports
#

# 3rd party module imports
#
import pytest
from moneyed import USD, Money

# Application imports
#
# from ..models import Bank, BankAccount, Budget, InternalTransaction, Transaction

pytestmark = pytest.mark.django_db


####################################################################
#
def test_internal_transaction(budget_factory, internal_transaction_factory):
    """
    Keyword Arguments:
    budget_factory               --
    internal_transaction_factory --
    """
    src_budget = budget_factory(balance=100)
    dst_budget = budget_factory(balance=100)
    it = internal_transaction_factory(
        amount=50, src_budget=src_budget, dst_budget=dst_budget
    )
    assert src_budget.balance == Money(50, USD)
    assert dst_budget.balance == Money(150, USD)
    assert it.src_budget_balance == Money(50, USD)
    assert it.dst_budget_balance == Money(150, USD)


####################################################################
#
def test_interanl_transaction_update(
    budget_factory, internal_transaction_factory
):
    """
    Keyword Arguments:
    budget_factory               --
    internal_transaction_factory --
    """
    src_budget = budget_factory(balance=100)
    dst_budget = budget_factory(balance=100)
    it = internal_transaction_factory(
        amount=50, src_budget=src_budget, dst_budget=dst_budget
    )
    assert it  # XXX Place holder for actual assertion
