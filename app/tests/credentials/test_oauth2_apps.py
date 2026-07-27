#!/usr/bin/env python
#
"""Tests for OAuth2 application registration.

Covers the /api/v1/users/me/oauth2-apps/ endpoints: ownership scoping,
the redirect-URI policy (the last place a plaintext remote callback can
be stopped, since ALLOWED_REDIRECT_URI_SCHEMES must keep http for RFC
8252 loopback), the one-time client secret, and the fields registration
deliberately refuses to take from the caller.
"""

# system imports
from collections.abc import Callable

# 3rd party imports
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

# Project imports
from credentials.models import AccessToken, Application
from users.models import User

pytestmark = pytest.mark.django_db

APPS_URL = reverse("api_v1:oauth2-app-list")


####################################################################
#
def app_url(application: Application) -> str:
    """Return the detail URL for an application."""
    return reverse(
        "api_v1:oauth2-app-detail",
        kwargs={"client_id": application.client_id},
    )


####################################################################
#
@pytest.fixture
def api_client(user: User) -> APIClient:
    """An interactively authenticated API client."""
    api_client = APIClient()
    api_client.force_authenticate(user=user)
    return api_client


########################################################################
########################################################################
#
class TestApplicationRegistration:
    """Tests for registering an OAuth2 application."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "client_type,secret_returned",
        [("public", False), ("confidential", True)],
    )
    def test_register(
        self,
        api_client: APIClient,
        user: User,
        client_type: str,
        secret_returned: bool,
    ):
        """
        GIVEN: an interactively authenticated user
        WHEN:  they register an application
        THEN:  it is owned by them, pinned to the authorization-code
               grant, and returns a client secret only if it is
               confidential (public clients cannot keep one -- they use
               PKCE).  Defaults for visibility/status are asserted by
               test_privileged_fields_are_not_settable, which pins them
               under the stronger condition of a caller trying to set
               them.
        """
        response = api_client.post(
            APPS_URL,
            {
                "name": "My Importer",
                "client_type": client_type,
                "redirect_uris": ["https://example.com/callback"],
            },
            format="json",
        )

        assert response.status_code == 201, response.data
        assert response.data["redirect_uris"] == [
            "https://example.com/callback"
        ]
        assert bool(response.data["client_secret"]) is secret_returned

        application = Application.objects.get(
            client_id=response.data["client_id"]
        )
        assert application.user == user
        assert (
            application.authorization_grant_type
            == Application.GRANT_AUTHORIZATION_CODE
        )

    ####################################################################
    #
    def test_client_secret_is_hashed_and_never_returned_again(
        self, api_client: APIClient
    ):
        """
        GIVEN: a newly registered confidential application
        WHEN:  it is retrieved after creation
        THEN:  the secret is absent from the read representation and the
               stored value is a hash, not the plaintext handed back
        """
        created = api_client.post(
            APPS_URL,
            {
                "name": "Hosted Importer",
                "client_type": "confidential",
                "redirect_uris": ["https://example.com/callback"],
            },
            format="json",
        )
        plaintext = created.data["client_secret"]
        assert plaintext

        application = Application.objects.get(
            client_id=created.data["client_id"]
        )
        assert application.client_secret != plaintext

        response = api_client.get(app_url(application))
        assert response.status_code == 200
        assert "client_secret" not in response.data

    ####################################################################
    #
    @pytest.mark.parametrize(
        "uri,accepted",
        [
            ("https://example.com/callback", True),
            # RFC 8252 loopback: native, desktop and MCP clients cannot
            # terminate TLS on a callback they spin up locally.
            ("http://127.0.0.1:8765/callback", True),
            ("http://[::1]:8765/callback", True),
            # Rejected: DOT only exempts the IP literals from exact port
            # matching, so a localhost URI registers and then fails for
            # any client binding an ephemeral port.
            ("http://localhost:8765/callback", False),
            # The hole the RFC 9700 redirect-scheme gate cannot close,
            # because http must stay allowed for loopback.
            ("http://example.com/callback", False),
            # RFC 6749: the redirect endpoint must not carry a fragment.
            ("https://example.com/callback#token", False),
            ("not-a-uri", False),
        ],
    )
    def test_redirect_uri_policy(
        self, api_client: APIClient, uri: str, accepted: bool
    ):
        """
        GIVEN: a redirect URI
        WHEN:  an application is registered with it
        THEN:  https and loopback http are accepted; a plaintext remote
               callback, a localhost URI, and a fragment are refused
        """
        response = api_client.post(
            APPS_URL,
            {
                "name": "App",
                "client_type": "public",
                "redirect_uris": [uri],
            },
            format="json",
        )

        assert response.status_code == (201 if accepted else 400), response.data
        if not accepted:
            assert "redirect_uris" in response.data

    ####################################################################
    #
    def test_privileged_fields_are_not_settable(
        self, api_client: APIClient, user: User
    ):
        """
        GIVEN: a registration request that also sets the fields only
               staff or the server may set
        WHEN:  the application is registered
        THEN:  those values are ignored -- a caller cannot promote their
               own app to global, publish it, skip the consent screen,
               or register a grant type this server refuses to serve
        """
        response = api_client.post(
            APPS_URL,
            {
                "name": "Sneaky",
                "client_type": "public",
                "redirect_uris": ["https://example.com/callback"],
                "visibility": Application.Visibility.GLOBAL,
                "status": Application.Status.PUBLISHED,
                "skip_authorization": True,
                "authorization_grant_type": Application.GRANT_PASSWORD,
                "user": 9999,
            },
            format="json",
        )

        assert response.status_code == 201, response.data
        application = Application.objects.get(
            client_id=response.data["client_id"]
        )
        assert application.visibility == Application.Visibility.PRIVATE
        assert application.status == Application.Status.TESTING
        assert application.skip_authorization is False
        assert (
            application.authorization_grant_type
            == Application.GRANT_AUTHORIZATION_CODE
        )
        assert application.user == user


########################################################################
########################################################################
#
class TestApplicationManagement:
    """Tests for listing, updating and deregistering applications."""

    ####################################################################
    #
    def test_scoped_to_own_applications(
        self,
        api_client: APIClient,
        user: User,
        user_factory: Callable[..., User],
        application_factory: Callable[..., Application],
    ):
        """
        GIVEN: applications registered by two different users
        WHEN:  one user lists applications and fetches the other's
        THEN:  only their own are listed; the other's is 404, not 403 --
               registrations are private, so their existence is not
               disclosed
        """
        mine = application_factory(user=user, name="Mine")
        theirs = application_factory(user=user_factory(), name="Theirs")

        response = api_client.get(APPS_URL)
        assert response.status_code == 200
        assert [a["name"] for a in response.data["results"]] == [mine.name]

        assert api_client.get(app_url(theirs)).status_code == 404
        assert api_client.delete(app_url(theirs)).status_code == 404

    ####################################################################
    #
    def test_update_name_and_redirect_uris(
        self,
        api_client: APIClient,
        user: User,
        application_factory: Callable[..., Application],
    ):
        """
        GIVEN: a registered application
        WHEN:  its name and redirect URIs are patched
        THEN:  both are updated, and the new URIs go through the same
               policy as registration
        """
        application = application_factory(user=user, name="Old")

        response = api_client.patch(
            app_url(application),
            {
                "name": "New",
                "redirect_uris": [
                    "https://example.com/a",
                    "http://127.0.0.1/b",
                ],
            },
            format="json",
        )
        assert response.status_code == 200, response.data

        # The response is the full read representation (matching
        # list/retrieve), not the write serializer's echo: redirect_uris
        # is a proper list, and the read-only fields are present.
        assert response.data["redirect_uris"] == [
            "https://example.com/a",
            "http://127.0.0.1/b",
        ]
        assert response.data["client_id"] == application.client_id
        assert response.data["name"] == "New"
        assert "visibility" in response.data
        assert "status" in response.data

        application.refresh_from_db()
        assert application.name == "New"
        assert application.redirect_uris.split() == [
            "https://example.com/a",
            "http://127.0.0.1/b",
        ]

        rejected = api_client.patch(
            app_url(application),
            {"redirect_uris": ["http://example.com/evil"]},
            format="json",
        )
        assert rejected.status_code == 400

    ####################################################################
    #
    def test_client_type_cannot_change(
        self,
        api_client: APIClient,
        user: User,
        application_factory: Callable[..., Application],
    ):
        """
        GIVEN: a registered public application
        WHEN:  a caller tries to switch it to confidential
        THEN:  the request is refused -- it changes how the app
               authenticates at the token endpoint, and the secret is
               only ever issued at registration
        """
        application = application_factory(
            user=user, client_type=Application.CLIENT_PUBLIC
        )

        response = api_client.patch(
            app_url(application),
            {"client_type": Application.CLIENT_CONFIDENTIAL},
            format="json",
        )

        assert response.status_code == 400
        assert "client_type" in response.data

    ####################################################################
    #
    def test_deregistering_revokes_issued_tokens(
        self,
        api_client: APIClient,
        user: User,
        application_factory: Callable[..., Application],
        access_token_factory: Callable[..., AccessToken],
        bearer_client: Callable[[str], APIClient],
    ):
        """
        GIVEN: an application with a live access token against it
        WHEN:  the owner deregisters the application
        THEN:  the token stops working -- deregistration is one of the
               two ways a grant ends, so it has to actually end it
        """
        application = application_factory(user=user)
        token = access_token_factory(user=user, application=application).token
        assert (
            bearer_client(token).get(reverse("api_v1:bank-list")).status_code
            == 200
        )

        assert api_client.delete(app_url(application)).status_code == 204

        assert (
            bearer_client(token).get(reverse("api_v1:bank-list")).status_code
            == 401
        )
        assert not Application.objects.filter(pk=application.pk).exists()
