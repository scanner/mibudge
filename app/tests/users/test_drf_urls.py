"""Tests for the users DRF API URL configuration."""

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
class TestUserAPIURLs:
    """Tests that users API URL names resolve to correct paths and view names."""

    def test_user_detail(self, user: User):
        """
        GIVEN: an existing user
        WHEN:  the api_v1:user-detail URL name is reversed and the resulting path
               is resolved
        THEN:  the path matches /api/v1/users/<username>/ and resolves to
               api_v1:user-detail
        """
        assert (
            reverse("api_v1:user-detail", kwargs={"username": user.username})
            == f"/api/v1/users/{user.username}/"
        )
        assert (
            resolve(f"/api/v1/users/{user.username}/").view_name
            == "api_v1:user-detail"
        )

    @pytest.mark.parametrize(
        "url_name,expected_path",
        [
            pytest.param("api_v1:user-list", "/api/v1/users/", id="list"),
            pytest.param("api_v1:user-me", "/api/v1/users/me/", id="me"),
        ],
    )
    def test_static_url_resolution(
        self, url_name: str, expected_path: str
    ) -> None:
        """
        GIVEN: an API URL name with a fixed (non-user-specific) path
        WHEN:  the name is reversed and the path is resolved
        THEN:  the path matches the expected value and resolves back to the
               same URL name
        """
        assert reverse(url_name) == expected_path
        assert resolve(expected_path).view_name == url_name
