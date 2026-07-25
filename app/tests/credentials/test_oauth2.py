#!/usr/bin/env python
#
"""Tests for OAuth2 access-token authentication.

Covers what is specific to the OAuth2 credential: rejection of invalid
tokens, including the active-user check django-oauth-toolkit does not
perform on its own.  The blocklist gate that OAuth2 tokens share with
API keys, and the coexistence of the OAuth2 and JWT bearer schemes, are
tested in test_permissions.py.

Token issuance (the /o/authorize/ + /o/token/ endpoints and the consent
screen) is not wired up yet, so tokens here are minted directly.
"""

# system imports
from collections.abc import Callable
from datetime import timedelta

# 3rd party imports
import pytest
from django.urls import reverse
from django.utils import timezone
from oauthlib.common import generate_token
from rest_framework.test import APIClient

# Project imports
from credentials.models import AccessToken
from users.models import User

pytestmark = pytest.mark.django_db

# A gate-free endpoint: read-only, available to any authenticated user,
# no fixtures required.
BANKS_URL = reverse("api_v1:bank-list")


########################################################################
########################################################################
#
class TestOAuth2Authentication:
    """Tests for the OAuth2Authentication DRF class."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "scenario", ["unknown", "expired", "inactive_user"]
    )
    def test_bad_credentials_rejected(
        self,
        user: User,
        access_token_factory: Callable[..., AccessToken],
        bearer_client: Callable[[str], APIClient],
        scenario: str,
    ):
        """
        GIVEN: a bearer token that is unknown, expired, or owned by a
               deactivated user
        WHEN:  a request is made with it
        THEN:  the request is rejected with 401

        NOTE: 'inactive_user' is the case DOT itself does not cover --
        it validates the token and hands back its user without checking
        is_active, so a disabled account would keep working through an
        outstanding grant were it not for our subclass.
        """
        match scenario:
            case "unknown":
                token = generate_token()
            case "expired":
                token = access_token_factory(
                    user=user, expires=timezone.now() - timedelta(seconds=1)
                ).token
            case "inactive_user":
                token = access_token_factory(user=user).token
                user.is_active = False
                user.save(update_fields=["is_active"])

        assert bearer_client(token).get(BANKS_URL).status_code == 401
