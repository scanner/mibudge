# system imports
from collections.abc import Callable
from datetime import date, datetime

# 3rd party imports
import pytest
from django.conf import settings
from pytest_factoryboy import register

# Project imports
from moneypools.models import BankAccount
from users.models import User

from .factories import (
    BankAccountFactory,
    BankAccountInvitationFactory,
    BankFactory,
    BudgetFactory,
    FundingEventOccurrenceFactory,
    InternalTransactionFactory,
    MerchantIntermediaryPatternFactory,
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
register(
    MerchantIntermediaryPatternFactory
)  # MerchantIntermediaryPatternFactory -> merchant_intermediary_pattern_factory


####################################################################
#
@pytest.fixture
def system_user() -> User:
    """Return the funding-system user seeded by migration 0024."""
    return User.objects.get(username=settings.FUNDING_SYSTEM_USERNAME)


####################################################################
#
@pytest.fixture
def make_account(
    bank_account_factory: Callable[..., BankAccount],
) -> Callable[..., BankAccount]:
    """Return a factory for bank accounts with optional freshness fields.

    Returns:
        A callable `(posted_through=None, imported_at=None) ->
        BankAccount` setting `last_posted_through` and
        `last_imported_at`.
    """

    def _make(
        posted_through: date | None = None,
        imported_at: datetime | None = None,
    ) -> BankAccount:
        return bank_account_factory(
            last_posted_through=posted_through,
            last_imported_at=imported_at,
        )

    return _make
