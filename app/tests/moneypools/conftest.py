# system imports
import itertools
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

# 3rd party imports
import pytest
from django.conf import settings
from djmoney.money import Money
from faker import Faker
from pytest_factoryboy import register

# Project imports
from moneypools.models import BankAccount, Budget
from moneypools.service import budget as budget_svc
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


########################################################################
########################################################################
#
@dataclass(frozen=True)
class MerchantPlace:
    """A made-up merchant location, in the shapes transactions carry it.

    `latitude` and `longitude` are strings with the six decimal places
    the `merchant_latitude` / `merchant_longitude` columns store.
    """

    city: str
    region: str
    street: str
    latitude: str
    longitude: str


####################################################################
#
@pytest.fixture
def merchant_place(faker: Faker) -> MerchantPlace:
    """A generated city, US state code, street and coordinates."""
    six_places = Decimal("0.000001")
    return MerchantPlace(
        city=faker.unique.city(),
        region=faker.state_abbr(include_territories=False),
        street=faker.street_address(),
        latitude=str(faker.latitude().quantize(six_places)),
        longitude=str(faker.longitude().quantize(six_places)),
    )


####################################################################
#
@pytest.fixture
def system_user() -> User:
    """Return the funding-system user seeded by migration 0024."""
    return User.objects.get(username=settings.FUNDING_SYSTEM_USERNAME)


####################################################################
#
@pytest.fixture
def account(
    bank_account_factory: Callable[..., BankAccount], user: User
) -> BankAccount:
    """A bank account owned by the default `user` fixture."""
    return bank_account_factory(owners=[user])


####################################################################
#
@pytest.fixture
def unallocated(account: BankAccount) -> Budget:
    """The Unallocated budget of `account`."""
    budget = account.unallocated_budget
    assert budget is not None
    return budget


####################################################################
#
@pytest.fixture
def make_goal(
    account: BankAccount, budget_factory: Callable[..., Budget]
) -> Callable[[], Budget]:
    """Return a factory for zero-balance Goal budgets on `account`.

    Each Goal funds $10 at a time toward a $100 target.

    Returns:
        A callable `() -> Budget`.
    """

    def _make() -> Budget:
        return budget_factory(
            bank_account=account,
            balance=Money(0, "USD"),
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            funding_amount=Money(10, "USD"),
            target_balance=Money(100, "USD"),
        )

    return _make


####################################################################
#
@pytest.fixture
def goal(make_goal: Callable[[], Budget]) -> Budget:
    """A zero-balance Goal budget on `account` (see `make_goal`)."""
    return make_goal()


####################################################################
#
@pytest.fixture
def make_account(
    bank_account_factory: Callable[..., BankAccount],
) -> Callable[..., BankAccount]:
    """Return a factory for bank accounts with optional freshness fields.

    Returns:
        A callable `(posted_through=None, imported_at=None,
        unallocated=None) -> BankAccount` setting `last_posted_through`
        and `last_imported_at`, and, when `unallocated` is given, the
        dollar balance of the account's Unallocated budget.
    """

    def _make(
        posted_through: date | None = None,
        imported_at: datetime | None = None,
        unallocated: int | None = None,
    ) -> BankAccount:
        account = bank_account_factory(
            last_posted_through=posted_through,
            last_imported_at=imported_at,
        )
        if unallocated is not None:
            assert account.unallocated_budget is not None
            Budget.objects.filter(pkid=account.unallocated_budget.pkid).update(
                balance=Money(unallocated, "USD")
            )
            account.refresh_from_db()
        return account

    return _make


####################################################################
#
@pytest.fixture
def make_budget() -> Callable[..., Budget]:
    """Return a factory for budgets created through the budget service.

    The service sets up fill-up goals, schedules and funding pointers as
    in production.  Tests then need the budget in some later state --
    a pointer moved, a balance or `funded_amount` reached, the fill-up
    part-filled -- which `stored` and `fillup` write straight to the
    rows afterwards.

    Returns:
        A callable `(bank_account, *, stored=None, fillup=None,
        **create_kwargs) -> Budget`.  `create_kwargs` pass through to
        `budget_svc.create` (a unique `name` is supplied when omitted);
        `stored` and `fillup` are field values written to the budget
        and to its fill-up goal.  The budget is returned freshly read,
        so `budget.fillup_goal` reflects the written state.
    """
    names = (f"Budget {n}" for n in itertools.count(1))

    def _make(
        bank_account: BankAccount,
        *,
        stored: dict[str, Any] | None = None,
        fillup: dict[str, Any] | None = None,
        **create_kwargs: Any,
    ) -> Budget:
        create_kwargs.setdefault("name", next(names))
        budget = budget_svc.create(bank_account=bank_account, **create_kwargs)
        if stored:
            Budget.objects.filter(pkid=budget.pkid).update(**stored)
        if fillup:
            budget.refresh_from_db()
            assert budget.fillup_goal is not None
            Budget.objects.filter(pkid=budget.fillup_goal.pkid).update(**fillup)
        budget.refresh_from_db()
        return budget

    return _make
