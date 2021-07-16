# system imports
#

# 3rd party module imports
#
import pytest
from moneyed import USD, Money

# Application imports
#
# from ..models import Bank, BankAccount, Budget, InternalTransaction, Transaction
from ..models import Budget

pytestmark = pytest.mark.django_db


####################################################################
#
def test_bank_account(bank_account_factory):
    bank_account = bank_account_factory()
    assert bank_account.unallocated_budget
    assert bank_account.unallocated_budget.bank_account == bank_account


####################################################################
#
def test_internal_transaction(budget_factory, internal_transaction_factory):
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
def test_internal_transaction_update(
    budget_factory, internal_transaction_factory
):
    """
    We are testing to see if changing the amount of an internal
    transaction after it has been created updates the balances of the
    src and dst budgets.
    """
    START_BAL = 100
    INITIAL_TRANSACTION_AMT = 50
    UPDATED_TRANSACTION_AMT = 75
    src_budget = budget_factory(balance=START_BAL)
    dst_budget = budget_factory(balance=START_BAL)
    it = internal_transaction_factory(
        amount=INITIAL_TRANSACTION_AMT,
        src_budget=src_budget,
        dst_budget=dst_budget,
    )
    it.amount = UPDATED_TRANSACTION_AMT
    it.save()
    src_budget = Budget.objects.get(id=src_budget.id)
    dst_budget = Budget.objects.get(id=dst_budget.id)

    SRC_BAL = START_BAL - UPDATED_TRANSACTION_AMT
    DST_BAL = START_BAL + UPDATED_TRANSACTION_AMT
    assert src_budget.balance == Money(SRC_BAL, USD)
    assert dst_budget.balance == Money(DST_BAL, USD)
    assert it.src_budget_balance == Money(SRC_BAL, USD)
    assert it.dst_budget_balance == Money(DST_BAL, USD)


####################################################################
#
def test_internal_transaction_budget_change(
    budget_factory, internal_transaction_factory
):
    """
    Test what happens if you update which budgets the src & dst point to.
    """
    START_BAL_A = 100
    START_BAL_B = 325

    TRANSACTION_AMT = 50

    src_budget_a = budget_factory(balance=START_BAL_A)
    dst_budget_a = budget_factory(balance=START_BAL_A)

    it = internal_transaction_factory(
        amount=TRANSACTION_AMT,
        src_budget=src_budget_a,
        dst_budget=dst_budget_a,
    )

    src_budget_b = budget_factory(balance=START_BAL_B)
    dst_budget_b = budget_factory(balance=START_BAL_B)

    it.src_budget = src_budget_b
    it.dst_budget = dst_budget_b
    it.save()

    src_budget_b = Budget.objects.get(id=src_budget_b.id)
    dst_budget_b = Budget.objects.get(id=dst_budget_b.id)

    assert src_budget_b.balance == Money(START_BAL_B - TRANSACTION_AMT, USD)
    assert dst_budget_b.balance == Money(START_BAL_B + TRANSACTION_AMT, USD)

    it.src_budget = src_budget_a
    it.save()
    src_budget_a = Budget.objects.get(id=src_budget_a.id)
    dst_budget_b = Budget.objects.get(id=dst_budget_b.id)

    assert src_budget_a.balance == Money(START_BAL_A - TRANSACTION_AMT, USD)
    assert dst_budget_b.balance == Money(START_BAL_B + TRANSACTION_AMT, USD)


####################################################################
#
def test_internal_transaction_delete(
    budget_factory, internal_transaction_factory
):
    src_budget = budget_factory(balance=100)
    dst_budget = budget_factory(balance=100)
    it = internal_transaction_factory(
        amount=50, src_budget=src_budget, dst_budget=dst_budget
    )
    assert src_budget.balance == Money(50, USD)
    assert dst_budget.balance == Money(150, USD)
    it.delete()
    src_budget = Budget.objects.get(id=src_budget.id)
    dst_budget = Budget.objects.get(id=dst_budget.id)
    assert src_budget.balance == Money(100, USD)
    assert dst_budget.balance == Money(100, USD)
