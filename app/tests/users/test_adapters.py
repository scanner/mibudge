#!/usr/bin/env python
#
"""Tests for the allauth adapter overrides in users/adapters.py."""

# 3rd party imports
#
import pytest
from django.test import RequestFactory

# Project imports
#
from users.adapters import AccountAdapter

pytestmark = pytest.mark.django_db


########################################################################
########################################################################
#
class TestSiteUrlRebasedUrls:
    """Adapter URLs must be rooted at SITE_URL, never the request host.

    Deployments sit behind proxies that rewrite the Host header to an
    internal name (e.g. the tailnet alias), so request-derived absolute
    URLs would leak that name into emails sent to external users.
    """

    ####################################################################
    #
    def test_password_reset_url_uses_site_url_origin(
        self,
        settings,
    ) -> None:
        """
        GIVEN: a request whose Host header is an internal deployment
               name different from the public SITE_URL
        WHEN:  the adapter builds the password-reset-from-key URL
        THEN:  the URL is rooted at SITE_URL's origin and the internal
               request host appears nowhere in it
        """
        settings.SITE_URL = "https://public.mibudge.test"
        settings.ALLOWED_HOSTS = ["internal.mibudge.test"]
        request = RequestFactory().get("/", HTTP_HOST="internal.mibudge.test")

        url = AccountAdapter(request).get_reset_password_from_key_url(
            "36u-abc123key"
        )

        assert url.startswith("https://public.mibudge.test/")
        assert "internal.mibudge.test" not in url
