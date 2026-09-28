"""Tests for users URL configuration."""

# 3rd party imports
#
import pytest
import pytest_check as check
from django.urls import resolve, reverse


########################################################################
########################################################################
#
class TestUserURLs:
    """Tests that users URL names resolve to correct paths and view names."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "url_name,kwargs,expected_path",
        [
            pytest.param(
                "users:detail",
                {"username": "alice"},
                "/users/alice/",
                id="detail",
            ),
            pytest.param("users:update", {}, "/users/~update/", id="update"),
            pytest.param(
                "users:redirect", {}, "/users/~redirect/", id="redirect"
            ),
        ],
    )
    def test_url_resolution(
        self, url_name: str, kwargs: dict[str, str], expected_path: str
    ) -> None:
        """
        GIVEN: a users URL name with optional kwargs
        WHEN:  the name is reversed and the resulting path is resolved
        THEN:  the path matches the expected value and resolves back to the
               same URL name
        """
        check.equal(reverse(url_name, kwargs=kwargs), expected_path, "reverses")
        check.equal(resolve(expected_path).view_name, url_name, "resolves back")
