"""Tests for top-level project URL configuration."""

# system imports
#

# 3rd party imports
#
import pytest
from django.urls import resolve, reverse

pytestmark = pytest.mark.django_db


########################################################################
########################################################################
#
class TestRootURLs:
    """Tests that root-level URL names resolve to correct paths and views."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "url_name,kwargs,expected_path,expected_view",
        [
            pytest.param(
                "token-refresh",
                {},
                "/api/token/refresh/",
                "token-refresh",
                id="token-refresh",
            ),
            pytest.param(
                "spa-shell",
                {},
                "/app/",
                "spa-shell",
                id="spa-shell",
            ),
            pytest.param(
                "spa-shell-subpath",
                {"subpath": "some/path"},
                "/app/some/path",
                "spa-shell-subpath",
                id="spa-shell-subpath",
            ),
        ],
    )
    def test_url_resolution(
        self,
        url_name: str,
        kwargs: dict[str, str],
        expected_path: str,
        expected_view: str,
    ) -> None:
        """
        GIVEN: a root-level URL name with optional kwargs
        WHEN:  the name is reversed and the resulting path is resolved
        THEN:  the path matches the expected value and resolves back to the
               same view name
        """
        assert reverse(url_name, kwargs=kwargs) == expected_path
        assert resolve(expected_path).view_name == expected_view
