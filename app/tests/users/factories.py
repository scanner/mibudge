from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import factory
from django.contrib.auth import get_user_model
from factory import Faker, post_generation
from factory.django import DjangoModelFactory

from users.models import UserInvitation


class UserFactory(DjangoModelFactory):
    username = Faker("user_name")
    email = Faker("email")
    name = Faker("name")

    @post_generation
    def password(
        self, create: bool, extracted: Sequence[Any], **kwargs
    ) -> None:
        password = (
            extracted
            if extracted
            else Faker(
                "password",
                length=42,
                special_chars=True,
                digits=True,
                upper_case=True,
                lower_case=True,
            ).evaluate(None, None, extra={"locale": None})
        )
        # factory-boy's @post_generation passes the model instance as self at
        # runtime, but stubs type it as the factory class -- revisit if factory-boy stubs improve
        self.set_password(password)  # type: ignore[attr-defined]
        if create:
            self.save()  # type: ignore[attr-defined]

    class Meta:
        model = get_user_model()
        django_get_or_create = ["email"]
        skip_postgeneration_save = True


class UserInvitationFactory(DjangoModelFactory):
    invited_by = factory.SubFactory(UserFactory)
    invitee_email = factory.Sequence(lambda n: f"invitee{n}@example.com")
    invitee_user = factory.SubFactory(UserFactory)
    token = factory.LazyFunction(
        lambda: __import__("secrets").token_urlsafe(48)
    )
    status = UserInvitation.Status.PENDING
    expires_at = factory.LazyFunction(
        lambda: datetime.now(UTC) + timedelta(days=7)
    )

    class Meta:
        model = UserInvitation
