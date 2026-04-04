"""Tests for users URL configuration."""

# system imports
#

# 3rd party imports
#
import pytest
from django.urls import resolve, reverse

# app imports
#
from users.models import User

pytestmark = pytest.mark.django_db


########################################################################
########################################################################
#
class TestUserURLs:
    """Tests that user URL names resolve to correct paths and view names."""

    def test_detail(self, user: User):
        """
        GIVEN: an existing user
        WHEN:  the users:detail URL name is reversed and the resulting path
               is resolved
        THEN:  the path matches /users/<username>/ and resolves to users:detail
        """
        assert (
            reverse("users:detail", kwargs={"username": user.username})
            == f"/users/{user.username}/"
        )
        assert resolve(f"/users/{user.username}/").view_name == "users:detail"

    @pytest.mark.parametrize(
        "url_name,expected_path",
        [
            pytest.param("users:update", "/users/~update/", id="update"),
            pytest.param("users:redirect", "/users/~redirect/", id="redirect"),
            pytest.param(
                "users:spa-login", "/users/~spa-login/", id="spa-login"
            ),
        ],
    )
    def test_static_url_resolution(
        self, url_name: str, expected_path: str
    ) -> None:
        """
        GIVEN: a users URL name with a fixed (non-user-specific) path
        WHEN:  the name is reversed and the path is resolved
        THEN:  the path matches the expected value and resolves back to the
               same URL name
        """
        assert reverse(url_name) == expected_path
        assert resolve(expected_path).view_name == url_name
