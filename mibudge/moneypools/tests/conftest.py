from pytest_factoryboy import register

from .factories import BankFactory, BankAccountFactory

register(BankFactory)
register(BankAccountFactory)
