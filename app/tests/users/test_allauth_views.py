#!/usr/bin/env python
#
"""
Smoke tests for allauth template rendering.

These verify that the allauth pages we rely on (password reset request,
reset-from-key, confirmation pages) render without errors.  The tests
are intentionally simple: a 500 here means a broken template dependency
(missing tag library, broken extends chain, etc.).
"""

# 3rd party imports
#
import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


########################################################################
########################################################################
#
class TestAllauthPageRendering:
    """Allauth pages render without errors (no auth required)."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "url_name",
        [
            "account_reset_password",
            "account_reset_password_done",
            "account_reset_password_from_key_done",
        ],
    )
    def test_get_returns_200(self, client, url_name: str) -> None:
        """
        GIVEN: an unauthenticated client
        WHEN:  GET to an allauth password-reset page
        THEN:  200 (template renders without errors)
        """
        response = client.get(reverse(url_name))

        assert response.status_code == 200

    ####################################################################
    #
    def test_password_reset_from_key_bad_token_renders(self, client) -> None:
        """
        GIVEN: an invalid reset key
        WHEN:  GET /accounts/password/reset/key/{uidb36}-{key}/
        THEN:  200; allauth renders the 'bad token' state without errors
        """
        url = reverse(
            "account_reset_password_from_key",
            kwargs={"uidb36": "AA", "key": "bad-key"},
        )

        response = client.get(url)

        assert response.status_code == 200
