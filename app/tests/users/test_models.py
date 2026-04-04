# system imports
#

# 3rd party imports
#
import pytest

# app imports
#
from users.models import User

pytestmark = pytest.mark.django_db


########################################################################
########################################################################
#
class TestUserModel:
    """Tests for the User model."""

    def test_get_absolute_url(self, user: User):
        """
        GIVEN: an existing user
        WHEN:  get_absolute_url() is called
        THEN:  the URL resolves to /users/<username>/
        """
        assert user.get_absolute_url() == f"/users/{user.username}/"
