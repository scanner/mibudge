"""Tests for users forms."""

# system imports
#

# 3rd party imports
#
import pytest
from django.utils.translation import gettext_lazy as _

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

    def test_duplicate_username_is_rejected(self, user: User):
        """
        GIVEN: an existing user in the database
        WHEN:  UserCreationForm is submitted with that user's username
        THEN:  the form is invalid, reports exactly one error on the username
               field, and the message says the username is already taken
        """
        form = UserCreationForm(
            {
                "username": user.username,
                "password1": user.password,
                "password2": user.password,
            }
        )

        assert not form.is_valid()
        assert len(form.errors) == 1
        assert "username" in form.errors
        assert form.errors["username"][0] == _(
            "This username has already been taken."
        )
