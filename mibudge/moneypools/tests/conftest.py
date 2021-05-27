from pytest_factoryboy import register

from .factories import BankFactory, BankAccountFactory, BudgetFactory

register(BankFactory)
register(BankAccountFactory)
register(BudgetFactory)
