from pytest_factoryboy import register

from .factories import (
    BankAccountFactory,
    BankFactory,
    BudgetFactory,
    InternalTransactionFactory,
    TransactionFactory,
)

register(BankFactory)
register(BankAccountFactory)
register(BudgetFactory)
register(TransactionFactory)
register(InternalTransactionFactory)
