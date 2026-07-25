#!/usr/bin/env python
#
"""Tests for API-key machine authentication.

Covers the APIKey model, the ApiKeyAuthentication DRF class, and the
key-management endpoints.  The RequiresInteractiveAuth gate is shared
with OAuth2 tokens and is tested in test_permissions.py.
"""

# system imports
from collections.abc import Callable
from datetime import timedelta

# 3rd party imports
import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

# Project imports
from credentials.models import APIKey
from users.models import User

from .factories import MintedAPIKey

pytestmark = pytest.mark.django_db

# The gate-free endpoint used to exercise authentication: read-only,
# available to any authenticated user, no fixtures required.
BANKS_URL = reverse("api_v1:bank-list")
API_KEYS_URL = reverse("api_v1:api-key-list")


########################################################################
########################################################################
#
class TestApiKeyAuthentication:
    """Tests for the APIKey model + ApiKeyAuthentication DRF class."""

    ####################################################################
    #
    def test_make_returns_plaintext_and_stores_only_hash(
        self, user: User, api_key_factory: Callable[..., MintedAPIKey]
    ):
        """
        GIVEN: a user
        WHEN:  APIKey.make() is called (as the factory does)
        THEN:  the plaintext is returned once, only its hash is stored,
               and the displayable prefix matches the plaintext
        """
        api_key = api_key_factory(user=user, name="test key")
        plaintext = api_key.plaintext

        assert plaintext.startswith(APIKey.KEY_PREFIX)
        assert api_key.hashed_key == APIKey.hash_key(plaintext)
        assert plaintext not in [api_key.hashed_key, api_key.prefix]
        assert api_key.prefix == plaintext[: APIKey.PREFIX_DISPLAY_LENGTH]
        assert api_key.expires_at is None
        assert api_key.is_active

    ####################################################################
    #
    @pytest.mark.parametrize(
        "scenario",
        ["unknown", "revoked", "expired", "inactive_user", "malformed"],
    )
    def test_bad_credentials_rejected(
        self,
        user: User,
        api_key_factory: Callable[..., MintedAPIKey],
        scenario: str,
    ):
        """
        GIVEN: a credential that is unknown, revoked, expired, owned by
               a deactivated user, or a malformed Api-Key header
        WHEN:  a request is made with it
        THEN:  the request is rejected with 401
        """
        match scenario:
            case "unknown":
                header = "Api-Key mib_not-a-real-key"
            case "revoked":
                api_key = api_key_factory(user=user, name=scenario)
                api_key.revoke()
                header = f"Api-Key {api_key.plaintext}"
            case "expired":
                api_key = api_key_factory(
                    user=user,
                    name=scenario,
                    expires_at=timezone.now() - timedelta(seconds=1),
                )
                header = f"Api-Key {api_key.plaintext}"
            case "inactive_user":
                api_key = api_key_factory(user=user, name=scenario)
                user.is_active = False
                user.save()
                header = f"Api-Key {api_key.plaintext}"
            case "malformed":
                header = "Api-Key"

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=header)
        assert client.get(BANKS_URL).status_code == 401

    ####################################################################
    #
    def test_last_used_updates_are_throttled(
        self,
        user: User,
        settings,
        api_key_factory: Callable[..., MintedAPIKey],
        api_key_client: Callable[[str], APIClient],
    ):
        """
        GIVEN: a key that was just used (last_used_at is fresh)
        WHEN:  a second request arrives inside the throttle interval
        THEN:  last_used_at is not written again; outside it, it is
        """
        api_key = api_key_factory(user=user, name="importer")
        client = api_key_client(api_key.plaintext)

        client.get(BANKS_URL)
        api_key.refresh_from_db()
        first_used = api_key.last_used_at
        assert first_used is not None

        # Inside the interval: no write.
        client.get(BANKS_URL)
        api_key.refresh_from_db()
        assert api_key.last_used_at == first_used

        # With the throttle disabled every request writes.
        settings.API_KEY_LAST_USED_THROTTLE = timedelta(seconds=0)
        client.get(BANKS_URL)
        api_key.refresh_from_db()
        assert api_key.last_used_at is not None
        assert api_key.last_used_at > first_used


########################################################################
########################################################################
#
class TestAPIKeyManagementAPI:
    """Tests for the /api/v1/users/me/api-keys/ endpoints."""

    ####################################################################
    #
    def test_create_returns_plaintext_once(self, user: User):
        """
        GIVEN: an interactively authenticated user
        WHEN:  a key is created via POST
        THEN:  the response includes the plaintext exactly once and the
               list endpoint never exposes it again
        """
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(API_KEYS_URL, {"name": "my importer"})
        assert response.status_code == 201
        assert response.data["key"].startswith(APIKey.KEY_PREFIX)
        assert response.data["name"] == "my importer"
        assert response.data["expires_at"] is None

        listing = client.get(API_KEYS_URL)
        assert listing.status_code == 200
        results = listing.data["results"]
        assert len(results) == 1
        assert "key" not in results[0]
        assert "hashed_key" not in results[0]

    ####################################################################
    #
    def test_create_with_expiry_days(self, user: User):
        """
        GIVEN: an interactively authenticated user
        WHEN:  a key is created with expiry_days set
        THEN:  expires_at lands that many days in the future
        """
        client = APIClient()
        client.force_authenticate(user=user)
        before = timezone.now() + timedelta(days=17)
        response = client.post(
            API_KEYS_URL, {"name": "expiring", "expiry_days": 17}
        )
        after = timezone.now() + timedelta(days=17)

        assert response.status_code == 201
        api_key = APIKey.objects.get(uuid=response.data["uuid"])
        assert api_key.expires_at is not None
        assert before <= api_key.expires_at <= after

    ####################################################################
    #
    def test_scoped_to_own_keys(
        self,
        user: User,
        user_factory: Callable[..., User],
        api_key_factory: Callable[..., MintedAPIKey],
    ):
        """
        GIVEN: keys belonging to two different users
        WHEN:  one user lists keys and tries to revoke the other's key
        THEN:  only their own keys are listed; the foreign key is 404
        """
        other = user_factory()
        api_key_factory(user=user, name="mine")
        theirs = api_key_factory(user=other, name="theirs")

        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(API_KEYS_URL)
        assert response.status_code == 200
        assert [k["name"] for k in response.data["results"]] == ["mine"]

        response = client.post(
            reverse("api_v1:api-key-revoke", kwargs={"uuid": theirs.uuid})
        )
        assert response.status_code == 404

    ####################################################################
    #
    def test_revoke(
        self, user: User, api_key_factory: Callable[..., MintedAPIKey]
    ):
        """
        GIVEN: an active key
        WHEN:  POST .../{uuid}/revoke/ is called, twice
        THEN:  the first call revokes it, the second returns 400
        """
        api_key = api_key_factory(user=user, name="doomed")
        client = APIClient()
        client.force_authenticate(user=user)
        revoke_url = reverse(
            "api_v1:api-key-revoke", kwargs={"uuid": api_key.uuid}
        )

        response = client.post(revoke_url)
        assert response.status_code == 200
        assert response.data["revoked_at"] is not None

        response = client.post(revoke_url)
        assert response.status_code == 400
