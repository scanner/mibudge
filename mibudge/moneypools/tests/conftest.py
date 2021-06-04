from pytest_factoryboy import register

from .factories import (
    BankFactory,
    BankAccountFactory,
    BudgetFactory,
    TransactionFactory,
    InternalTransactionFactory,
)

register(BankFactory)
register(BankAccountFactory)
register(BudgetFactory)
register(TransactionFactory)
register(InternalTransactionFactory)
