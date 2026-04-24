import random
import string
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import factory
import factory.fuzzy
from django.contrib.auth import get_user_model
from djmoney.money import Money
from factory.django import DjangoModelFactory

from moneypools.models import (
    Bank,
    BankAccount,
    Budget,
    InternalTransaction,
    Transaction,
    TransactionAllocation,
    TransactionCategory,
    get_default_currency,
)
from moneypools.service import budget as budget_svc
from moneypools.service import internal_transaction as internal_transaction_svc
from moneypools.service import (
    transaction_allocation as transaction_allocation_svc,
)

# XXX If we want to separate 'moneypools' into its own app we will
#     need to sever this link (and I guess add a UserFactory to our
#     `factories.py`)
#
from tests.users.factories import UserFactory

User = get_user_model()

_BANK_SUFFIXES = [" Bank", " Credit Union", " Trust"]


####################################################################
#
def random_string(length: int, character_set: str) -> str:
    """
    Generate a random string of from the given character set up to
    `length` characters long.
    """
    return "".join(random.choice(character_set) for _ in range(length))


########################################################################
####################################################################
#
class BankFactory(DjangoModelFactory):
    class Meta:
        model = Bank
        django_get_or_create = ["name"]
        exclude = ["company_base"]

    company_base = factory.Faker("company")
    name = factory.LazyAttribute(
        lambda o: o.company_base + random.choice(_BANK_SUFFIXES)
    )
    routing_number = factory.LazyAttribute(
        lambda x: random_string(9, string.digits)
    )


########################################################################
####################################################################
#
class BankAccountFactory(DjangoModelFactory):
    class Meta:
        model = BankAccount
        django_get_or_create = ["account_number"]
        # owners post-generation only calls .add() on an M2M -- no model
        # field mutation, so the auto-save after hooks is extraneous.
        skip_postgeneration_save = True

    # XXX This is generating people names not bank account names... we
    #     should do something like "Name's Checking Account" etc. and
    #     append the last 4 digits of teh account_number.. so maybe
    #     this becomes a `@post_generate` function
    #
    name = factory.Faker("name")
    account_number = factory.LazyAttribute(
        lambda x: random_string(12, string.digits)
    )
    account_type = factory.LazyAttribute(
        lambda x: random.choice(BankAccount.BankAccountType.values)
    )

    bank = factory.SubFactory(BankFactory)

    @factory.post_generation
    # get_user_model() returns a type expression, not a concrete class, so
    # it cannot be used as a type annotation -- revisit if django-stubs improve
    def owners(self, create: bool, extracted: Sequence[User], **kwargs) -> None:  # type: ignore[valid-type]
        if not create:
            return
        if extracted:
            # A list of users were passed in, use them
            for user in extracted:
                self.owners.add(user)
        else:
            self.owners.add(UserFactory())


########################################################################
########################################################################
#
class BudgetFactory(DjangoModelFactory):
    class Meta:
        model = Budget
        exclude = ("has_target_date", "target_balance_offset")
        # _create calls BudgetService.create so fill-up goal creation
        # and other service-layer invariants are exercised by tests.

    name = factory.Faker("name")
    bank_account = factory.SubFactory(BankAccountFactory)
    balance = factory.fuzzy.FuzzyInteger(100, 2000)
    target_balance_offset = factory.fuzzy.FuzzyInteger(100, 1000)
    target_balance = factory.LazyAttribute(lambda self: 200)
    budget_type = factory.fuzzy.FuzzyChoice(Budget.BudgetType.values)
    funding_type = factory.fuzzy.FuzzyChoice(Budget.FundingType.values)
    # NOTE: This attribute is not part of the model. Instead this is
    # used to create a boolean that can be tested to see if the
    # 'funding type' for this budget is 'by a target date' (instead of
    # 'fixed amount per funding schedule')
    #
    has_target_date = factory.LazyAttribute(
        lambda x: (
            True
            if factory.SelfAttribute("funding_type")
            == Budget.FundingType.TARGET_DATE
            else False
        )
    )
    target_date = factory.Maybe(
        "has_target_date",
        yes_declaration=factory.fuzzy.FuzzyDateTime(
            start_dt=datetime.now(UTC) + timedelta(days=15),
            end_dt=datetime.now(UTC) + timedelta(days=90),
        ),
        no_declaration=None,
    )

    @classmethod
    def _create(cls, model_class: type, *args: object, **kwargs: Any) -> Budget:
        bank_account = kwargs.pop("bank_account")
        name = kwargs.pop("name")
        budget_type = kwargs.pop("budget_type")
        funding_type = kwargs.pop("funding_type")
        target_balance = kwargs.pop("target_balance")

        return budget_svc.create(
            bank_account=bank_account,
            name=name,
            budget_type=budget_type,
            funding_type=funding_type,
            target_balance=target_balance,
            **kwargs,
        )


########################################################################
########################################################################
#
class TransactionFactory(DjangoModelFactory):
    class Meta:
        model = Transaction

    bank_account = factory.SubFactory(BankAccountFactory)
    amount = factory.fuzzy.FuzzyInteger(100, 200)
    transaction_date = factory.fuzzy.FuzzyDateTime(
        start_dt=datetime.now(UTC) - timedelta(days=365),
        end_dt=datetime.now(UTC),
    )
    transaction_type = factory.fuzzy.FuzzyChoice(
        Transaction.TransactionType.values
    )
    raw_description = factory.fuzzy.FuzzyText(length=100)


########################################################################
########################################################################
#
class TransactionAllocationFactory(DjangoModelFactory):
    class Meta:
        model = TransactionAllocation

    transaction = factory.SubFactory(TransactionFactory)
    budget = factory.SubFactory(BudgetFactory)
    amount = factory.LazyAttribute(lambda o: o.transaction.amount)
    category = factory.fuzzy.FuzzyChoice(TransactionCategory.values)

    @classmethod
    def _create(
        cls, model_class: type, *args: object, **kwargs: Any
    ) -> TransactionAllocation:
        transaction = kwargs.pop("transaction")
        budget = kwargs.pop("budget")
        amount = kwargs.pop("amount")
        if not hasattr(amount, "amount"):
            amount = Money(amount, get_default_currency())
        return transaction_allocation_svc.create(
            transaction=transaction,
            budget=budget,
            amount=amount,
            **kwargs,
        )


########################################################################
########################################################################
#
class InternalTransactionFactory(DjangoModelFactory):
    class Meta:
        model = InternalTransaction

    bank_account = factory.SubFactory(BankAccountFactory)
    amount = factory.fuzzy.FuzzyInteger(100, 200)
    src_budget = factory.SubFactory(BudgetFactory)
    dst_budget = factory.SubFactory(BudgetFactory)
    actor = factory.SubFactory(UserFactory)

    @classmethod
    def _create(
        cls, model_class: type, *args: object, **kwargs: Any
    ) -> InternalTransaction:
        amount = kwargs["amount"]
        if not hasattr(amount, "amount"):
            amount = Money(amount, get_default_currency())

        return internal_transaction_svc.create(
            bank_account=kwargs["bank_account"],
            src_budget=kwargs["src_budget"],
            dst_budget=kwargs["dst_budget"],
            amount=amount,
            actor=kwargs["actor"],
        )
