#!/usr/bin/env python
#
"""Tests for the server-rendered OAuth2 authorization-code + PKCE flow.

Covers the endpoints mounted in credentials/urls.py end to end: the
flow's own login page, the consent screen, the token/refresh/revoke
endpoints, and the RFC 8414 discovery document.  Also pins the two
policy decisions that are easy to regress -- that unauthenticated
visitors are sent to the OAuth2 login rather than the SPA, and that the
endpoints and flows this server does not offer stay unmounted and
unadvertised.
"""

# system imports
import base64
import hashlib
import secrets
from collections.abc import Callable
from urllib.parse import parse_qs, urlparse

# 3rd party imports
import pytest
from django.test import Client
from django.urls import reverse

# Project imports
from credentials.models import AccessToken, Application
from users.models import User

pytestmark = pytest.mark.django_db

PASSWORD = "correct-horse-battery-staple-42"
REDIRECT_URI = "https://example.com/callback"
LOGIN_URL = "/o/login/"
AUTHORIZE_URL = "/o/authorize/"
TOKEN_URL = "/o/token/"
REVOKE_URL = "/o/revoke_token/"
METADATA_URL = "/.well-known/oauth-authorization-server"


####################################################################
#
def pkce_pair() -> tuple[str, str]:
    """Return an S256 (code_verifier, code_challenge) pair.

    Returns:
        The verifier the client keeps, and the challenge it sends with
        the authorization request.
    """
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


####################################################################
#
def authorization_params(application: Application, challenge: str) -> dict:
    """Return the query parameters for an authorization request."""
    return {
        "response_type": "code",
        "client_id": application.client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": "read write",
        "state": "opaque-client-state",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }


####################################################################
#
def redirect_query(response) -> dict[str, list[str]]:
    """Return the parsed query string of a redirect response."""
    return parse_qs(urlparse(response["Location"]).query)


####################################################################
#
@pytest.fixture
def oauth2_user(user_factory: Callable[..., User]) -> User:
    """A user whose password is known, so the login form can be driven."""
    return user_factory(password=PASSWORD)


####################################################################
#
@pytest.fixture
def oauth2_app(
    application_factory: Callable[..., Application],
    user_factory: Callable[..., User],
) -> Application:
    """A registered public auth-code app owned by some other user."""
    return application_factory(
        name="Test Importer",
        user=user_factory(),
        redirect_uris=REDIRECT_URI,
    )


####################################################################
#
@pytest.fixture
def logged_in_client(oauth2_user: User) -> Client:
    """A client holding a session from the OAuth2 login page.

    Drives the real login form rather than force_login() so the flow's
    own login view is exercised on the way to every consent test.
    """
    client = Client()
    response = client.post(
        LOGIN_URL,
        {"username": oauth2_user.email, "password": PASSWORD, "next": "/o/"},
    )
    assert response.status_code == 302, "login form rejected the credentials"
    return client


####################################################################
#
@pytest.fixture
def granted_tokens(
    logged_in_client: Client, oauth2_app: Application
) -> Callable[[], dict]:
    """Return a callable that completes a full flow and returns tokens.

    Runs authorize -> consent -> code exchange with a fresh PKCE pair
    each call, so a test can mint more than one grant.
    """

    def _grant() -> dict:
        verifier, challenge = pkce_pair()
        params = authorization_params(oauth2_app, challenge)

        consent = logged_in_client.get(AUTHORIZE_URL, params)
        assert consent.status_code == 200

        approval = logged_in_client.post(
            AUTHORIZE_URL, {**params, "allow": "Authorize"}
        )
        assert approval.status_code == 302
        code = redirect_query(approval)["code"][0]

        token_response = logged_in_client.post(
            TOKEN_URL,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": oauth2_app.client_id,
                "code_verifier": verifier,
            },
        )
        assert token_response.status_code == 200, token_response.content
        return token_response.json()

    return _grant


########################################################################
########################################################################
#
class TestAuthorizationFlow:
    """Tests for the authorization-code + PKCE flow."""

    ####################################################################
    #
    def test_unauthenticated_authorize_redirects_to_oauth2_login(
        self, oauth2_app: Application
    ):
        """
        GIVEN: a visitor with no Django session
        WHEN:  they follow a 3rd-party app's link to /o/authorize/
        THEN:  they are sent to the OAuth2 flow's own login page, NOT to
               the SPA login -- the SPA issues a JWT and no session, so
               sending them there would loop back here forever
        """
        _, challenge = pkce_pair()

        response = Client().get(
            AUTHORIZE_URL, authorization_params(oauth2_app, challenge)
        )

        assert response.status_code == 302
        assert response["Location"].startswith(LOGIN_URL)
        assert "/app/login/" not in response["Location"]

    ####################################################################
    #
    def test_consent_screen_names_the_app_and_its_scopes(
        self, logged_in_client: Client, oauth2_app: Application
    ):
        """
        GIVEN: a signed-in user following an authorization request
        WHEN:  the consent screen is rendered
        THEN:  it names the requesting application and describes every
               scope it asked for, so consent is informed -- rendered by
               mibudge's styled template, not DOT's unstyled default
        """
        _, challenge = pkce_pair()

        response = logged_in_client.get(
            AUTHORIZE_URL, authorization_params(oauth2_app, challenge)
        )

        assert response.status_code == 200
        body = response.content.decode()
        assert oauth2_app.name in body
        assert "Read access to your budgeting data" in body
        assert "Read and write access to your budgeting data" in body
        # The project template dir must win over DOT's app template of
        # the same name, so the page inherits the mibudge shell.
        assert "credentials/oauth2_base.html" in [
            template.name for template in response.templates
        ]

    ####################################################################
    #
    def test_granted_access_token_authenticates_api_requests(
        self, granted_tokens: Callable[[], dict], oauth2_user: User
    ):
        """
        GIVEN: a completed authorization-code + PKCE exchange
        WHEN:  the returned access token is used against the REST API
        THEN:  it authenticates as the user who granted it, and the
               response carries a refresh token for later renewal
        """
        tokens = granted_tokens()

        assert tokens["token_type"] == "Bearer"
        assert tokens["refresh_token"]
        assert tokens["scope"] == "read write"

        response = Client().get(
            reverse("api_v1:user-me"),
            headers={"authorization": f"Bearer {tokens['access_token']}"},
        )
        assert response.status_code == 200
        assert response.json()["username"] == oauth2_user.username

    ####################################################################
    #
    def test_refresh_token_exchange_rotates_the_token(
        self, granted_tokens: Callable[[], dict], oauth2_app: Application
    ):
        """
        GIVEN: a grant's refresh token
        WHEN:  it is exchanged for a new access token
        THEN:  a working access token comes back and the refresh token
               is rotated (ROTATE_REFRESH_TOKEN), so the old one is
               single-use
        """
        tokens = granted_tokens()

        response = Client().post(
            TOKEN_URL,
            {
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": oauth2_app.client_id,
            },
        )

        assert response.status_code == 200, response.content
        refreshed = response.json()
        assert refreshed["access_token"] != tokens["access_token"]
        assert refreshed["refresh_token"] != tokens["refresh_token"]

        api = Client().get(
            reverse("api_v1:bank-list"),
            headers={"authorization": f"Bearer {refreshed['access_token']}"},
        )
        assert api.status_code == 200

    ####################################################################
    #
    def test_revocation_invalidates_the_access_token(
        self, granted_tokens: Callable[[], dict], oauth2_app: Application
    ):
        """
        GIVEN: a granted access token
        WHEN:  it is revoked at /o/revoke_token/
        THEN:  it stops authenticating API requests -- revocation is the
               only way a grant ends, so it has to actually work
        """
        tokens = granted_tokens()
        header = {"authorization": f"Bearer {tokens['access_token']}"}
        assert (
            Client()
            .get(reverse("api_v1:bank-list"), headers=header)
            .status_code
            == 200
        )

        response = Client().post(
            REVOKE_URL,
            {
                "token": tokens["access_token"],
                "client_id": oauth2_app.client_id,
            },
        )
        assert response.status_code == 200

        assert (
            Client()
            .get(reverse("api_v1:bank-list"), headers=header)
            .status_code
            == 401
        )
        assert not AccessToken.objects.filter(
            token=tokens["access_token"]
        ).exists()

    ####################################################################
    #
    def test_denying_consent_returns_access_denied(
        self, logged_in_client: Client, oauth2_app: Application
    ):
        """
        GIVEN: a user on the consent screen
        WHEN:  they choose Cancel (the POST carries no 'allow')
        THEN:  they are redirected back to the app with access_denied
               and no grant is created
        """
        _, challenge = pkce_pair()
        params = authorization_params(oauth2_app, challenge)

        response = logged_in_client.post(AUTHORIZE_URL, params)

        assert response.status_code == 302
        query = redirect_query(response)
        assert query["error"] == ["access_denied"]
        assert "code" not in query
        assert not oauth2_app.grant_set.exists()

    ####################################################################
    #
    @pytest.mark.parametrize(
        "override,enforced_at",
        [
            # PKCE_REQUIRED is checked while validating the authorization
            # request, so a missing challenge never reaches consent.
            (
                {"code_challenge": None, "code_challenge_method": None},
                "request",
            ),
            # COMPLIANT_BCP_RFC9700_PKCE_METHOD rejects 'plain' (which
            # sends the verifier in the clear) in DOT's
            # _create_authorization_code, i.e. only once the user
            # approves.  Consent renders first; no code is ever issued.
            ({"code_challenge_method": "plain"}, "grant"),
        ],
    )
    def test_pkce_policy_is_enforced(
        self,
        logged_in_client: Client,
        oauth2_app: Application,
        override: dict,
        enforced_at: str,
    ):
        """
        GIVEN: an authorization request that violates the PKCE policy
        WHEN:  it is taken as far as the policy allows
        THEN:  it is refused with invalid_request and no authorization
               code or grant is created -- the flow is never quietly
               downgraded to a weaker one
        """
        _, challenge = pkce_pair()
        params = authorization_params(oauth2_app, challenge)
        for key, value in override.items():
            if value is None:
                params.pop(key)
            else:
                params[key] = value

        response = logged_in_client.get(AUTHORIZE_URL, params)
        if enforced_at == "grant":
            assert response.status_code == 200
            response = logged_in_client.post(
                AUTHORIZE_URL, {**params, "allow": "Authorize"}
            )

        assert response.status_code == 302
        query = redirect_query(response)
        assert query["error"] == ["invalid_request"]
        assert "code" not in query
        assert not oauth2_app.grant_set.exists()


########################################################################
########################################################################
#
class TestOAuth2LoginView:
    """Tests for the OAuth2 flow's own login page."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "scenario", ["wrong_password", "unknown_email", "inactive_user"]
    )
    def test_bad_credentials_rejected(self, oauth2_user: User, scenario: str):
        """
        GIVEN: credentials that are wrong, unknown, or belong to a
               deactivated account
        WHEN:  they are submitted to the OAuth2 login form
        THEN:  the form is re-rendered with an error and no session is
               established
        """
        credentials = {"username": oauth2_user.email, "password": PASSWORD}
        match scenario:
            case "wrong_password":
                credentials["password"] = "not-the-password"
            case "unknown_email":
                credentials["username"] = "nobody@example.com"
            case "inactive_user":
                oauth2_user.is_active = False
                oauth2_user.save(update_fields=["is_active"])

        client = Client()
        response = client.post(LOGIN_URL, credentials)

        assert response.status_code == 200
        assert "_auth_user_id" not in client.session

    ####################################################################
    #
    def test_repeated_failures_are_throttled(self, oauth2_user: User, settings):
        """
        GIVEN: a login page that accepts passwords and is reachable
               without authentication
        WHEN:  an address exceeds its failed-attempt budget
        THEN:  further attempts are refused with 429, even with the
               correct password -- an unthrottled password form here
               would be a brute-force oracle
        """
        settings.OAUTH2_LOGIN_MAX_ATTEMPTS = 3
        client = Client()
        wrong = {"username": oauth2_user.email, "password": "wrong"}

        for _ in range(3):
            assert client.post(LOGIN_URL, wrong).status_code == 200

        assert client.post(LOGIN_URL, wrong).status_code == 429
        correct = {"username": oauth2_user.email, "password": PASSWORD}
        assert client.post(LOGIN_URL, correct).status_code == 429

    ####################################################################
    #
    def test_successful_login_clears_the_failure_count(
        self, oauth2_user: User, settings
    ):
        """
        GIVEN: some failed attempts that have not yet hit the limit
        WHEN:  the user signs in successfully
        THEN:  the counter resets, so a user who mistypes and then
               succeeds is not throttled on their next visit
        """
        settings.OAUTH2_LOGIN_MAX_ATTEMPTS = 3
        client = Client()
        client.post(LOGIN_URL, {"username": oauth2_user.email, "password": "x"})
        client.post(LOGIN_URL, {"username": oauth2_user.email, "password": "x"})

        credentials = {"username": oauth2_user.email, "password": PASSWORD}
        assert client.post(LOGIN_URL, credentials).status_code == 302

        Client().post(
            LOGIN_URL, {"username": oauth2_user.email, "password": "x"}
        )
        assert Client().post(LOGIN_URL, credentials).status_code == 302


########################################################################
########################################################################
#
class TestOAuth2Discovery:
    """Tests for the RFC 8414 metadata document and endpoint surface."""

    ####################################################################
    #
    def test_metadata_advertises_only_supported_capabilities(self):
        """
        GIVEN: the RFC 8414 discovery document
        WHEN:  a client fetches it
        THEN:  it advertises exactly the flows this server accepts.  A
               document that lists implicit/password/device sends
               clients down flows that will be rejected
        """
        response = Client().get(METADATA_URL)

        assert response.status_code == 200
        data = response.json()
        assert data["grant_types_supported"] == [
            "authorization_code",
            "refresh_token",
        ]
        assert data["response_types_supported"] == ["code"]
        assert data["code_challenge_methods_supported"] == ["S256"]
        assert data["authorization_endpoint"].endswith(AUTHORIZE_URL)
        assert data["token_endpoint"].endswith(TOKEN_URL)
        assert data["revocation_endpoint"].endswith(REVOKE_URL)
        # Not mounted, so not advertised.
        assert "introspection_endpoint" not in data
        assert "registration_endpoint" not in data

    ####################################################################
    #
    @pytest.mark.parametrize(
        "path",
        [
            # RFC 8628 device flow -- deliberately deferred.
            "/o/device/",
            "/o/device-authorization/",
            # DOT's own HTML management screens -- the SPA owns these.
            "/o/applications/",
            "/o/authorized_tokens/",
            # Not an identity provider, and no dynamic registration.
            "/o/userinfo/",
            "/o/introspect/",
        ],
    )
    def test_unoffered_endpoints_are_not_mounted(self, path: str):
        """
        GIVEN: DOT ships endpoints for flows and screens mibudge does
               not offer
        WHEN:  one of them is requested
        THEN:  it 404s -- they are left unmounted rather than exposed
               unstyled or half-supported
        """
        assert Client().get(path).status_code == 404


########################################################################
########################################################################
#
class TestApplicationAdmin:
    """Tests for the Application admin screens."""

    ####################################################################
    #
    @pytest.mark.parametrize("page", ["changelist", "change"])
    def test_admin_pages_render(
        self,
        oauth2_app: Application,
        user_factory: Callable[..., User],
        page: str,
    ):
        """
        GIVEN: a registered application
        WHEN:  staff open its admin changelist or change page
        THEN:  the pages render

        NOTE: this is a regression test with teeth.  DOT's
        AbstractApplication.get_absolute_url() reverses its own
        application-detail view, which credentials/urls.py deliberately
        does not mount, so the admin's 'View on site' link raises
        NoReverseMatch unless view_on_site is disabled.
        """
        staff = user_factory(is_staff=True, is_superuser=True)
        client = Client()
        client.force_login(staff)

        if page == "changelist":
            url = reverse("admin:credentials_application_changelist")
        else:
            url = reverse(
                "admin:credentials_application_change", args=[oauth2_app.pk]
            )

        response = client.get(url)

        assert response.status_code == 200
        assert b"View on site" not in response.content
