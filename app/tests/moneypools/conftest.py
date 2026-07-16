import pytest
from pytest_factoryboy import register
from rest_framework.test import APIClient

from users.models import User

from .factories import (
    BankAccountFactory,
    BankAccountInvitationFactory,
    BankFactory,
    BudgetFactory,
    FundingEventOccurrenceFactory,
    InternalTransactionFactory,
    TransactionAllocationFactory,
    TransactionCategoryFactory,
    TransactionFactory,
)

register(BankFactory)  # BankFactory -> bank_factory
register(BankAccountFactory)  # BankAccountFactory -> bank_account_factory
register(BudgetFactory)  # BudgetFactory -> budget_factory
register(TransactionFactory)  # TransactionFactory -> transaction_factory
register(
    TransactionCategoryFactory
)  # TransactionCategoryFactory -> transaction_category_factory
register(
    TransactionAllocationFactory
)  # TransactionAllocationFactory -> transaction_allocation_factory
register(
    InternalTransactionFactory
)  # InternalTransactionFactory -> internal_transaction_factory
register(
    FundingEventOccurrenceFactory
)  # FundingEventOccurrenceFactory -> funding_event_occurrence_factory
register(
    BankAccountInvitationFactory
)  # BankAccountInvitationFactory -> bank_account_invitation_factory


@pytest.fixture
def api_client() -> APIClient:
    """An unauthenticated DRF test client."""
    return APIClient()


@pytest.fixture
def auth_client(user: User) -> APIClient:
    """A DRF test client authenticated as the default ``user`` fixture."""
    client = APIClient()
    client.force_authenticate(user=user)
    return client
