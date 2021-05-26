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
from ..models import Bank, BankAccount

User = get_user_model()

faker = FakerFactory.create()

# Because I want bank names, not random strings, or people names, but
# not real bank names, but things that sound like bank names:
# https://www.fantasynamegenerators.com/bank-names.php
#
# XXX This is cute and all but maybe we should just use the 'business
#     name' generator in `faker` and add one of 'Bank', `Credit
#     Union`, or `Trust` to the end of the generated names.
#
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
    return "".join(random.choice(character_set) for _ in range(length))


####################################################################
#
class BankFactory(DjangoModelFactory):
    name = factory.LazyAttribute(lambda x: random.choice(BANK_NAMES))
    routing_number = factory.LazyAttribute(
        lambda x: random_string(9, string.digits)
    )

    class Meta:
        model = Bank
        django_get_or_create = ["name"]  # XXX Maybe should be routing_number?


####################################################################
#
class BankAccountFactory(DjangoModelFactory):

    # XXX This is generating people names not bank account names... we
    #     should do something like "Name's Checking Account" etc. and
    #     append the last 4 digits of teh account_number.. so maybe
    #     this becomes a `@post_generate` function
    #
    name = factory.LazyAttribute(lambda x: faker.name())
    account_number = factory.LazyAttribute(
        lambda x: random_string(12, string.digits)
    )
    account_type = factory.LazyAttribute(
        lambda x: random.choice(list(BankAccount.BankAccountType.values.keys()))
    )

    bank = factory.SubFactory(BankFactory)

    @factory.post_generation
    def owners(self, create: bool, extracted: Sequence[User], **kwargs):
        if not create:
            return
        if extracted:
            # A list of users were passed in, use them
            for user in extracted:
                self.owners.add(user)
        else:
            self.owners.add(UserFactory())

    class Meta:
        model = BankAccount
        django_get_or_create = ["account_number"]
