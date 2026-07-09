#!/usr/bin/env python
#
"""Tests for API-key machine authentication.

Covers the APIKey model, the ApiKeyAuthentication DRF class, the
key-management endpoints, and the RequiresInteractiveAuth blocklist
gate on user/security endpoints.
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
from users.models import APIKey, User

pytestmark = pytest.mark.django_db

# The gate-free endpoint used to exercise authentication: read-only,
# available to any authenticated user, no fixtures required.
BANKS_URL = reverse("api_v1:bank-list")
API_KEYS_URL = reverse("api_v1:api-key-list")


####################################################################
#
def key_client(plaintext: str) -> APIClient:
    """Return an APIClient sending the given plaintext API key."""
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Api-Key {plaintext}")
    return client


########################################################################
########################################################################
#
class TestApiKeyAuthentication:
    """Tests for the APIKey model + ApiKeyAuthentication DRF class."""

    ####################################################################
    #
    def test_make_returns_plaintext_and_stores_only_hash(self, user: User):
        """
        GIVEN: a user
        WHEN:  APIKey.make() is called
        THEN:  the plaintext is returned once, only its hash is stored,
               and the displayable prefix matches the plaintext
        """
        api_key, plaintext = APIKey.make(user, "test key")

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
    def test_bad_credentials_rejected(self, user: User, scenario: str):
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
                api_key, plaintext = APIKey.make(user, scenario)
                api_key.revoke()
                header = f"Api-Key {plaintext}"
            case "expired":
                _, plaintext = APIKey.make(
                    user,
                    scenario,
                    expires_at=timezone.now() - timedelta(seconds=1),
                )
                header = f"Api-Key {plaintext}"
            case "inactive_user":
                _, plaintext = APIKey.make(user, scenario)
                user.is_active = False
                user.save()
                header = f"Api-Key {plaintext}"
            case "malformed":
                header = "Api-Key"

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=header)
        assert client.get(BANKS_URL).status_code == 401

    ####################################################################
    #
    def test_last_used_updates_are_throttled(self, user: User, settings):
        """
        GIVEN: a key that was just used (last_used_at is fresh)
        WHEN:  a second request arrives inside the throttle interval
        THEN:  last_used_at is not written again; outside it, it is
        """
        api_key, plaintext = APIKey.make(user, "importer")
        client = key_client(plaintext)

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
        self, user: User, user_factory: Callable[..., User]
    ):
        """
        GIVEN: keys belonging to two different users
        WHEN:  one user lists keys and tries to revoke the other's key
        THEN:  only their own keys are listed; the foreign key is 404
        """
        other = user_factory()
        APIKey.make(user, "mine")
        theirs, _ = APIKey.make(other, "theirs")

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
    def test_revoke(self, user: User):
        """
        GIVEN: an active key
        WHEN:  POST .../{uuid}/revoke/ is called, twice
        THEN:  the first call revokes it, the second returns 400
        """
        api_key, _ = APIKey.make(user, "doomed")
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


########################################################################
########################################################################
#
class TestRequiresInteractiveAuth:
    """Tests for the machine-credential blocklist gate."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "method,url_name,expected_status",
        [
            # Sensitive user/security endpoints: machine creds denied.
            ("patch", "api_v1:user-me", 403),
            ("post", "api_v1:user-change-password", 403),
            ("post", "api_v1:user-change-email", 403),
            ("get", "api_v1:user-my-invitations", 403),
            ("get", "api_v1:api-key-list", 403),
            ("post", "api_v1:api-key-list", 403),
            # Profile reads + budgeting domain: allowed.
            ("get", "api_v1:user-me", 200),
            ("get", "api_v1:bank-list", 200),
            ("get", "api_v1:bankaccount-list", 200),
        ],
    )
    def test_api_key_access_by_endpoint(
        self, user: User, method: str, url_name: str, expected_status: int
    ):
        """
        GIVEN: a valid API key
        WHEN:  a v1 endpoint is accessed with it
        THEN:  user/security endpoints deny the machine credential
               with 403, while profile reads and budgeting-domain
               endpoints allow it
        """
        _, plaintext = APIKey.make(user, "importer")
        response = getattr(key_client(plaintext), method)(reverse(url_name))
        assert response.status_code == expected_status

    ####################################################################
    #
    def test_api_key_can_read_own_profile(self, user: User):
        """
        GIVEN: a valid API key
        WHEN:  GET /users/me/ is requested with it
        THEN:  the profile body includes the fields machine consumers
               rely on (importers read the timezone)
        """
        _, plaintext = APIKey.make(user, "importer")
        response = key_client(plaintext).get(reverse("api_v1:user-me"))
        assert response.status_code == 200
        assert response.data["username"] == user.username
        assert response.data["timezone"] == user.timezone
