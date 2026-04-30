import pytest
from pytest_factoryboy import register
from rest_framework.test import APIClient

from .factories import (
    BankAccountFactory,
    BankFactory,
    BudgetFactory,
    InternalTransactionFactory,
    TransactionAllocationFactory,
    TransactionFactory,
)

register(BankFactory)  # BankFactory -> bank_factory
register(BankAccountFactory)  # BankAccountFactory -> bank_account_factory
register(BudgetFactory)  # BudgetFactory -> budget_factory
register(TransactionFactory)  # TransactionFactory -> transaction_factory
register(
    TransactionAllocationFactory
)  # TransactionAllocationFactory -> transaction_allocation_factory
register(
    InternalTransactionFactory
)  # InternalTransactionFactory -> internal_transaction_factory


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()
