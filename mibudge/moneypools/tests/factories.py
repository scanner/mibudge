import random
import string
from typing import Any, Sequence

import factory
from factory.django import DjangoModelFactory
from faker import Factory as FakerFactory

from django.contrib.auth import get_user_model

# XXX If we want to separate 'moneypools' into its own app we will
#     need to sever this link (and I guess add a UserFactory to our
#     `factories.py`)
#
from mibudge.users.tests.factories import UserFactory

User = get_user_model()

faker = FakerFactory.create()

BANK_NAMES = [
    "United Credit Union",
    "Gold Credit Bank System",
    "Solace Bank Group",
    "Ascension Bank Inc.",
    "New Alliance Banks Inc.",
    "New Heights Bank System",
    "Marshall Trust Corp.",
    "Epitome Banks Inc.",
    "Spotlight Trust Corp.",
    "New Connection Trust",
    "Ocean Trust",
    "Vigor Trust Corp.",
    "Connection Banks",
    "First Choice Corporation",
    "Fountain Bancshares",
    "Ascension Trust Corp.",
    "Soul Financial Corp.",
    "Spotlight Financial Holdings",
    "Associated Bank Group",
    "Citizen Service Banks Inc.",
    "Edge Corporation",
    "Goldleaf Holdings Inc.",
    "Credit Holdings Inc.",
    "Genesis Credit Union",
    "Syndicate Holdings",
    "Marshall Corporation",
    "Federal Corporation",
    "New Generation Financial Corp.",
    "First Credit Union",
    "Community Bancorp",
]


####################################################################
#
def random_string(length: int, character_set: str) -> str:
    """
    Generate a random string of from the given character set up to
    `length` characters long.
    """
    return ''.join(random.choice(character_set) for _ in range(length))


####################################################################
#
class BankFactory(DjangoModelFactory):
    name = factory.LazyAttribute(lambda x: random.choice(BANK_NAMES))
    routing_number = factory.LazyAttribute(random_string(9, string.digits))

    class Meta:
        model = 'moneypools.Bank'
        django_get_or_create = ["username"]


####################################################################
#
class BankAccountFactory(DjangoModelFactory):
    # XXX This is generating people names not bank account names... we
    #     should do something like "Name's Checking Account" etc. and
    #     append the last 4 digits of teh account_number.. so maybe
    #     this becomes a `@post_generate` function
    #
    name = factory.LazyAttribute(lambda x: faker.name())
    account_number = factory.LazyAttribute(random_string(12, string.digits))
    account_type = factory.LazyAttribute(lambda x: random.choice['C', 'S'])

    @factory.post_generation
    def bank(self, create: bool, extracted: Sequence[Any], **kwargs):
        bank = (
            extracted if extracted else factory.SubFactory(BankFactory)
        )
        self.set_bank(bank)

    @factory.post_generation
    def owners(self, create: bool, extracted: Sequence[User], **kwargs):
        owners = (
            extracted if extracted else UserFactory()
        )
        self.set_owners(owners)

    @factory.post_generation
    def posted_balance(self, create: bool, extracted: int, **kwargs):
        posted_balance = (
            extracted if extracted else 0
        )
        self.set_posted_balance(posted_balance)

    @factory.post_generation
    def available_balance(self, create: bool, extracted: int, **kwargs):
        available_balance = (
            extracted if extracted else 0
        )
        self.set_available_balance(available_balance)

    @factory.post_generation
    def unallocated_balance(self, create: bool, extracted: int, **kwargs):
        unallocated_balance = (
            extracted if extracted else 0
        )
        self.set_unallocated_balance(unallocated_balance)

    class Meta:
        model = 'moneypools.BankAccount'
