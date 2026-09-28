"""Tests for the users DRF API URL configuration."""

# 3rd party imports
#
import pytest
import pytest_check as check
from django.urls import resolve, reverse


########################################################################
########################################################################
#
class TestUserAPIURLs:
    """Tests that users API URL names resolve to correct paths and view names."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "url_name,kwargs,expected_path",
        [
            pytest.param(
                "api_v1:user-detail",
                {"username": "alice"},
                "/api/v1/users/alice/",
                id="detail",
            ),
            pytest.param("api_v1:user-list", {}, "/api/v1/users/", id="list"),
            pytest.param("api_v1:user-me", {}, "/api/v1/users/me/", id="me"),
        ],
    )
    def test_url_resolution(
        self, url_name: str, kwargs: dict[str, str], expected_path: str
    ) -> None:
        """
        GIVEN: a users API URL name with optional kwargs
        WHEN:  the name is reversed and the resulting path is resolved
        THEN:  the path matches the expected value and resolves back to the
               same URL name
        """
        check.equal(reverse(url_name, kwargs=kwargs), expected_path, "reverses")
        check.equal(resolve(expected_path).view_name, url_name, "resolves back")
