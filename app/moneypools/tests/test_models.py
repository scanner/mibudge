# system imports
#

# 3rd party module imports
#
import pytest
from moneyed import USD, Money

# Application imports
#
# from ..models import Bank, BankAccount, Budget, InternalTransaction, Transaction
from ..models import BankAccount, Budget, Transaction

pytestmark = pytest.mark.django_db


####################################################################
#
def test_bank_account(bank_account_factory):
    bank_account = bank_account_factory()
    assert bank_account.unallocated_budget
    assert bank_account.unallocated_budget.bank_account == bank_account

    BANK_AVAIL_BAL = 900
    BANK_POSTED_BAL = 1000
    bank_account = bank_account_factory(
        available_balance=BANK_AVAIL_BAL, posted_balance=BANK_POSTED_BAL
    )
    assert bank_account.posted_balance == Money(BANK_POSTED_BAL, USD)
    assert bank_account.available_balance == Money(BANK_AVAIL_BAL, USD)


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

    with pytest.raises(ValueError):
        it = internal_transaction_factory(
            amount=-50, src_budget=src_budget, dst_budget=dst_budget
        )


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


####################################################################
#
def test_transaction(bank_account_factory, transaction_factory):
    """
    A non-internal transaction.. simulate money being withdrawn from
    an account. Check the amount in the default 'unallocated budget'
    both when the transaction is pending and when it is not pending
    (ie: posted)

    Keyword Arguments:
    bank_factory        --
    budget_factory      --
    transaction_factory --
    """
    BANK_AVAIL_BAL = 900
    BANK_POSTED_BAL = 1000
    TRANSACTION_AMT = -100
    bank_account = bank_account_factory(
        available_balance=BANK_AVAIL_BAL, posted_balance=BANK_POSTED_BAL
    )
    transaction = transaction_factory(
        amount=TRANSACTION_AMT,
        pending=True,
        raw_description="This is a transaction",
        bank_account=bank_account,
    )
    assert transaction.bank_account.available_balance == Money(
        BANK_AVAIL_BAL + TRANSACTION_AMT, USD
    )
    assert transaction.bank_account.posted_balance == Money(
        BANK_POSTED_BAL, USD
    )
    assert transaction.budget_balance == transaction.budget.balance
    assert (
        bank_account.unallocated_budget.balance
        == bank_account.available_balance
    )
    assert transaction.budget == bank_account.unallocated_budget
    transaction.pending = False
    transaction.save()
    assert transaction.bank_account.available_balance == Money(
        BANK_AVAIL_BAL + TRANSACTION_AMT, USD
    )
    assert transaction.bank_account.posted_balance == Money(
        BANK_POSTED_BAL + TRANSACTION_AMT, USD
    )


####################################################################
#
def test_transaction_amount_change(bank_account_factory, transaction_factory):
    """
    The case where we are updating the amount of a non-internal
    transaction. This typically only happens when a transaction for a
    certain amount when it is pending is different from the amount
    when it is no longer pending (like using a debit card to buy gas)
    """
    BANK_AVAIL_BAL = 900
    BANK_POSTED_BAL = 1000
    TRANSACTION_AMT = -100
    FINAL_TRANSACTION_AMT = -28.43
    bank_account = bank_account_factory(
        available_balance=BANK_AVAIL_BAL, posted_balance=BANK_POSTED_BAL
    )
    transaction = transaction_factory(
        amount=TRANSACTION_AMT,
        pending=True,
        raw_description="This is a transaction",
        bank_account=bank_account,
    )
    transaction.save()

    upd_trans = Transaction.objects.get(id=transaction.id)
    upd_trans.amount = Money(FINAL_TRANSACTION_AMT, USD)
    upd_trans.pending = False
    upd_trans.save()

    ba = BankAccount.objects.get(id=bank_account.id)

    assert upd_trans.budget_balance == upd_trans.budget.balance
    assert ba.unallocated_budget.balance == ba.available_balance
    assert upd_trans.budget == ba.unallocated_budget
    assert upd_trans.bank_account.available_balance == Money(
        BANK_AVAIL_BAL + FINAL_TRANSACTION_AMT, USD
    )
    assert upd_trans.bank_account.posted_balance == Money(
        BANK_POSTED_BAL + FINAL_TRANSACTION_AMT, USD
    )
    assert ba.available_balance == Money(
        BANK_AVAIL_BAL + FINAL_TRANSACTION_AMT, USD
    )
    assert ba.posted_balance == Money(
        BANK_POSTED_BAL + FINAL_TRANSACTION_AMT, USD
    )


####################################################################
#
def test_transaction_pending_change(bank_account_factory, transaction_factory):
    """
    A transaction goes from pending to posted.. budget amounts do not
    change but the banks "avail" and "posted" amounts change.
    """
    BANK_AVAIL_BAL = 1000
    BANK_POSTED_BAL = 1000
    TRANSACTION_AMT = -100
    bank_account = bank_account_factory(
        available_balance=BANK_AVAIL_BAL, posted_balance=BANK_POSTED_BAL
    )
    transaction = transaction_factory(
        amount=TRANSACTION_AMT,
        pending=True,
        raw_description="This is a transaction",
        bank_account=bank_account,
    )
    transaction.save()

    ba = BankAccount.objects.get(id=bank_account.id)
    assert ba.posted_balance == Money(BANK_POSTED_BAL, USD)
    assert ba.available_balance == Money(BANK_AVAIL_BAL + TRANSACTION_AMT, USD)
    assert ba.unallocated_budget.balance == ba.available_balance

    upd_trans = Transaction.objects.get(id=transaction.id)
    upd_trans.pending = False
    upd_trans.save()

    ba = BankAccount.objects.get(id=bank_account.id)

    assert ba.posted_balance == Money(BANK_POSTED_BAL + TRANSACTION_AMT, USD)
    assert ba.available_balance == Money(BANK_AVAIL_BAL + TRANSACTION_AMT, USD)
    assert ba.unallocated_budget.balance == ba.available_balance


####################################################################
#
def test_transaction_budget_change(
    bank_account_factory,
    budget_factory,
    transaction_factory,
    internal_transaction_factory,
):
    """
    A common case (the most common case?) is some time after a
    transaction is recorded the budget that it is associated with is
    change.. ie: by default it was associated with the default
    "unallocated budget" but later it was was associated with the
    "gasoline" budget.
    """
    BANK_AVAIL_BAL = 1000
    BANK_POSTED_BAL = 1000
    TRANSACTION_AMT = -100
    bank_account = bank_account_factory(
        available_balance=BANK_AVAIL_BAL, posted_balance=BANK_POSTED_BAL
    )

    # Make our dest budget and make sure it has money in it.
    #
    dst_budget = budget_factory(balance=0)
    it = internal_transaction_factory(
        amount=abs(TRANSACTION_AMT),
        src_budget=bank_account.unallocated_budget,
        dst_budget=dst_budget,
    )
    assert it.amount == Money(abs(TRANSACTION_AMT), USD)
    assert dst_budget.balance == Money(abs(TRANSACTION_AMT), USD)

    transaction = transaction_factory(
        amount=TRANSACTION_AMT,
        pending=True,
        raw_description="This is a transaction",
        bank_account=bank_account,
    )
    transaction.save()

    upd_trans = Transaction.objects.get(id=transaction.id)
    upd_trans.budget = dst_budget
    upd_trans.pending = False
    upd_trans.save()

    ba = BankAccount.objects.get(id=bank_account.id)
    dst_budget = Budget.objects.get(id=dst_budget.id)
    assert ba.unallocated_budget.balance == Money(
        BANK_POSTED_BAL + TRANSACTION_AMT, USD
    )
    assert dst_budget.balance == Money(0, USD)
    assert ba.posted_balance == Money(BANK_POSTED_BAL + TRANSACTION_AMT, USD)
    assert ba.available_balance == Money(BANK_AVAIL_BAL + TRANSACTION_AMT, USD)


####################################################################
#
def test_transaction_delete(bank_account_factory, transaction_factory):
    """
    Should never happen in the normal case of things but debugging and
    fixing may involve deleting transactions so deleting a transaction
    should do the right thing with respect to bank account and buget
    balances.
    """
    BANK_AVAIL_BAL = 900
    BANK_POSTED_BAL = 1000
    TRANSACTION_AMT = -100
    bank_account = bank_account_factory(
        available_balance=BANK_AVAIL_BAL, posted_balance=BANK_POSTED_BAL
    )
    transaction = transaction_factory(
        amount=TRANSACTION_AMT,
        pending=True,
        raw_description="This is a transaction",
        bank_account=bank_account,
    )
    transaction.delete()
    ba = BankAccount.objects.get(id=bank_account.id)
    assert ba.posted_balance == Money(BANK_POSTED_BAL, USD)
    assert ba.available_balance == Money(BANK_AVAIL_BAL, USD)

    transaction = transaction_factory(
        amount=TRANSACTION_AMT,
        pending=False,
        raw_description="This is a transaction",
        bank_account=bank_account,
    )
    transaction.delete()
    ba = BankAccount.objects.get(id=bank_account.id)
    assert ba.posted_balance == Money(BANK_POSTED_BAL, USD)
    assert ba.available_balance == Money(BANK_AVAIL_BAL, USD)
