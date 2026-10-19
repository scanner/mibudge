#!/usr/bin/env python
#
"""Test how the server reports the release it runs."""

# 3rd party imports
#
import pytest
import pytest_check as check
from django.test import Client
from django.urls import reverse
from pytest_django.fixtures import SettingsWrapper
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

VERSION = "9.8.7"


####################################################################
#
@pytest.fixture(autouse=True)
def release(settings: SettingsWrapper) -> None:
    """Every test in this module runs on release `VERSION`."""
    settings.MIBUDGE_VERSION = VERSION


########################################################################
########################################################################
#
class TestServerVersionEndpoint:
    """Tests for `GET /api/version/`."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "authorization",
        [None, "Bearer not-a-valid-token"],
        ids=["no-credentials", "invalid-credentials"],
    )
    def test_reports_release_and_api_versions(
        self, api_client: APIClient, authorization: str | None
    ) -> None:
        """
        GIVEN: a server running a release
        WHEN:  a client asks for the version, with no credentials or
               with credentials that are not valid
        THEN:  it gets the release and the API versions served
        """
        if authorization:
            api_client.credentials(HTTP_AUTHORIZATION=authorization)

        resp = api_client.get(reverse("server-version"))

        assert resp.status_code == 200
        assert resp.json() == {"version": VERSION, "api_versions": ["v1"]}


########################################################################
########################################################################
#
class TestServerVersionHeader:
    """Tests for the `X-Mibudge-Version` response header."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "url,status",
        [
            (reverse("server-version"), 200),
            ("/api/v1/banks/", 401),
        ],
        ids=["success", "error"],
    )
    def test_api_responses_carry_release(
        self, api_client: APIClient, url: str, status: int
    ) -> None:
        """
        GIVEN: a server running a release
        WHEN:  a client gets any API response, an error included
        THEN:  the response names the release in `X-Mibudge-Version`
        """
        resp = api_client.get(url)

        assert resp.status_code == status
        assert resp["X-Mibudge-Version"] == VERSION


########################################################################
########################################################################
#
class TestLandingPage:
    """Tests for the release shown on the landing page."""

    ####################################################################
    #
    def test_landing_page_shows_release(self, client: Client) -> None:
        """
        GIVEN: a server running a release
        WHEN:  a browser loads the landing page
        THEN:  its footer shows the release, and the page, not being an
               API response, has no `X-Mibudge-Version` header
        """
        resp = client.get(reverse("home"))

        assert resp.status_code == 200
        check.is_in(
            f"mibudge {VERSION} &mdash;", resp.content.decode(), "footer"
        )
        check.is_false(resp.has_header("X-Mibudge-Version"), "no header")
