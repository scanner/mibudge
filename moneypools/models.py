from django.db import models


########################################################################
########################################################################
#
class MoneyPoolBaseClass(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


########################################################################
########################################################################
#
class Bank(MoneyPoolBaseClass):
    """
    We are dealing with your money stored in bank accounts in the
    banks you have accounts with.
    """
    name = models.CharField(max_length=200)


########################################################################
########################################################################
#
class BankAccount(MoneyPoolBaseClass):
    """
    This app is about budgeting your money but as a view in to your
    bank account's money. Thus the fundamental aspect of a Budget is
    which bank account it is tied to.
    """
    name = models.CharField(max_length=200)
    bank = models.ForeignKey(Bank, on_delete=models.CASCADE)


########################################################################
########################################################################
#
# NOTE: we must make sure that there is always a 'safe to spend'
# budget. It is displayed somewhat specially.
#
class Budget(MoneyPoolBaseClass):
    """
    """
    name = models.CharField(max_length=200)
    bank_account = models.ForeignKey(BankAccount, on_delete=models.CASCADE)
    # photo
    # memo
    # auto-spend
    # target_amount
    # due_date


########################################################################
########################################################################
#
class TransactionBaseClass(MoneyPoolBaseClass):
    # amount

    class Meta:
        abstract = True


########################################################################
########################################################################
#
class ThirdPartyTransaction(TransactionBaseClass):
    """
    A transaction detailing a credit/debit from some 3rd party
    NOTE: if this is associated with a budget, deleting the budget moves it back to the 'safe to spend' budget.
    """
    party = models.CharField(max_length=300)
    # memo
    # amount
    # state (pending or not)
    # category
    # photo
    # document


########################################################################
########################################################################
#
class InternalTransaction(TransactionBaseClass):
    """
    An internal transaction moving money between budgets
    """
    # src_goal
    # dest_goal
