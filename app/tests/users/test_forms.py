"""Tests for users forms."""

# system imports
#

# 3rd party imports
#
import pytest
import pytest_check as check
from django.utils.translation import gettext_lazy as _
from faker import Faker

# app imports
#
from users.forms import UserCreationForm
from users.models import User

pytestmark = pytest.mark.django_db


########################################################################
########################################################################
#
class TestUserCreationForm:
    """Tests for the UserCreationForm."""

    def test_duplicate_username_is_rejected(
        self, user: User, faker: Faker
    ) -> None:
        """
        GIVEN: an existing user in the database
        WHEN:  UserCreationForm is submitted with that user's username
        THEN:  the form is invalid, reports exactly one error on the username
               field, and the message says the username is already taken
        """
        password = faker.password(length=20)
        form = UserCreationForm(
            {
                "username": user.username,
                "email": faker.unique.email(),
                "password1": password,
                "password2": password,
            }
        )

        check.is_false(form.is_valid(), "form is invalid")
        check.equal(
            form.errors,
            {"username": [_("This username has already been taken.")]},
            "only because the username is taken",
        )
