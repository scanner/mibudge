"""
DRF authentication for machine credentials.

API keys are long-lived machine credentials (see credentials.models.APIKey)
sent as ``Authorization: Api-Key <key>``.  They authenticate as the
key's owning user; ``request.auth`` is set to the APIKey instance,
which is how the RequiresInteractiveAuth permission distinguishes
machine credentials from interactive JWT sessions.

OAuth2 access tokens issued to registered 3rd-party apps arrive as
``Authorization: Bearer <token>`` and are handled by
django-oauth-toolkit; the OAuth2Authentication subclass here adds the
active-user check DOT omits.  It sets ``request.auth`` to an
AccessToken, the other half of the RequiresInteractiveAuth blocklist.
"""

# system imports
import logging

# 3rd party imports
from django.utils import timezone
from drf_spectacular.contrib.django_oauth_toolkit import (
    DjangoOAuthToolkitScheme,
)
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from oauth2_provider.contrib.rest_framework import (
    OAuth2Authentication as DOTOAuth2Authentication,
)
from rest_framework.authentication import (
    BaseAuthentication,
    get_authorization_header,
)
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

# Project imports
from credentials.models import AccessToken, APIKey
from users.models import User

logger = logging.getLogger("credentials.authentication")


########################################################################
########################################################################
#
class ApiKeyAuthentication(BaseAuthentication):
    """Authenticate requests bearing ``Authorization: Api-Key <key>``.

    Returns None (passes to the next authenticator) unless the
    Authorization header uses the ``Api-Key`` keyword, so it coexists
    with JWT ``Bearer`` authentication.
    """

    keyword = "Api-Key"

    ####################################################################
    #
    def authenticate(self, request: Request) -> tuple[User, APIKey] | None:
        """Authenticate the request from its Api-Key header, if present.

        Args:
            request: The incoming DRF request.

        Returns:
            (user, api_key) on success, or None if the request does not
            carry an Api-Key authorization header.

        Raises:
            AuthenticationFailed: If the header is malformed, the key is
                unknown, revoked, or expired, or the user is inactive.
        """
        expected = self.keyword.lower().encode()
        match get_authorization_header(request).split():
            case [keyword, raw_key] if keyword.lower() == expected:
                pass
            case [keyword, *_] if keyword.lower() == expected:
                raise AuthenticationFailed(
                    "Invalid Api-Key header. Expected 'Api-Key <key>'."
                )
            case _:
                # Not ours (no header, or a different scheme such as
                # Bearer) -- pass to the next authenticator.
                return None
        try:
            key = raw_key.decode()
        except UnicodeDecodeError as exc:
            raise AuthenticationFailed(
                "Invalid Api-Key header. Key contains invalid characters."
            ) from exc

        try:
            api_key = APIKey.objects.select_related("user").get(
                hashed_key=APIKey.hash_key(key)
            )
        except APIKey.DoesNotExist as exc:
            raise AuthenticationFailed("Invalid API key.") from exc

        match (api_key.is_revoked, api_key.is_expired, api_key.user.is_active):
            case (True, _, _):
                raise AuthenticationFailed("API key has been revoked.")
            case (_, True, _):
                raise AuthenticationFailed("API key has expired.")
            case (_, _, False):
                raise AuthenticationFailed("User inactive or deleted.")

        self._touch_last_used(api_key)
        return (api_key.user, api_key)

    ####################################################################
    #
    def authenticate_header(self, request: Request) -> str:
        """Return the WWW-Authenticate scheme for 401 responses."""
        return self.keyword

    ####################################################################
    #
    @staticmethod
    def _touch_last_used(api_key: APIKey) -> None:
        """Update last_used_at, throttled to one write per interval.

        Bulk imports make thousands of requests in minutes; writing on
        every request would swamp the table.  A queryset update is used
        so ``modified_at`` (auto_now) is not bumped by usage tracking.
        """
        from django.conf import settings

        now = timezone.now()
        if (
            api_key.last_used_at is not None
            and now - api_key.last_used_at < settings.API_KEY_LAST_USED_THROTTLE
        ):
            return
        APIKey.objects.filter(pk=api_key.pk).update(last_used_at=now)


########################################################################
########################################################################
#
class OAuth2Authentication(DOTOAuth2Authentication):
    """DOT's OAuth2 authentication, plus an active-user check.

    django-oauth-toolkit validates the token but never looks at
    ``user.is_active`` -- it hands back the token's user regardless.
    Both other authenticators here reject deactivated users (simplejwt
    in ``get_user()``, ApiKeyAuthentication explicitly), so without this
    an OAuth2 grant would be the one credential that survives
    deactivating an account.

    NOTE: revocation of the grant itself is DOT's job (the token row is
    deleted or its ``expires`` passes); this only covers the case where
    the *user* is disabled while grants are outstanding.
    """

    ####################################################################
    #
    def authenticate(self, request: Request) -> tuple[User, AccessToken] | None:
        """Authenticate the bearer token, rejecting inactive users.

        Args:
            request: The incoming DRF request.

        Returns:
            (user, access_token) on success, or None if the request
            carries no valid OAuth2 bearer token (a JWT, for instance),
            so that the next authenticator gets a chance at it.

        Raises:
            AuthenticationFailed: If the token is valid but its user has
                been deactivated.
        """
        result = super().authenticate(request)
        if result is None:
            return None

        user, access_token = result
        if not user.is_active:
            raise AuthenticationFailed("User inactive or deleted.")
        return (user, access_token)


########################################################################
########################################################################
#
class OAuth2AuthenticationScheme(DjangoOAuthToolkitScheme):
    """Point drf-spectacular's DOT scheme at our subclass.

    OpenApiAuthenticationExtension matches on the exact class by
    default, so the stock DOT extension would not fire for
    OAuth2Authentication above and the schema would lose its oauth2
    security scheme.
    """

    target_class = "credentials.authentication.OAuth2Authentication"

    ####################################################################
    #
    def get_security_definition(self, auto_schema: object) -> dict:
        """Return DOT's oauth2 scheme plus mibudge's usage notes.

        The flows themselves are built by DOT's extension from the
        SPECTACULAR OAUTH2_* settings; only the description is added
        here, so the endpoints and scopes stay generated rather than
        duplicated.

        Args:
            auto_schema: The drf-spectacular AutoSchema being built.

        Returns:
            The OpenAPI security scheme object.
        """
        definition = super().get_security_definition(auto_schema)
        definition["description"] = (
            "Delegated access for registered 3rd-party apps and MCP "
            "servers, granted by a user rather than handed to them.\n\n"
            "Authorization code + PKCE only, and PKCE is mandatory "
            "(S256; `plain` is rejected). The implicit, password, "
            "client-credentials and device grants are all refused. "
            "Access tokens last 60 minutes and must be sent as "
            "`Authorization: Bearer <token>`; refresh tokens do not "
            "expire on a timer and rotate on every use, so a grant ends "
            "only when the user revokes it at `/o/revoke_token/`.\n\n"
            "Endpoints are discoverable at "
            "`/.well-known/oauth-authorization-server` (RFC 8414). "
            "OAuth2 tokens are machine credentials: they reach the "
            "budgeting domain but are refused on user/security "
            "endpoints."
        )
        return definition


########################################################################
########################################################################
#
class ApiKeyAuthenticationScheme(OpenApiAuthenticationExtension):
    """drf-spectacular security scheme for ApiKeyAuthentication."""

    target_class = "credentials.authentication.ApiKeyAuthentication"
    name = "apiKeyAuth"

    ####################################################################
    #
    def get_security_definition(self, auto_schema: object) -> dict[str, str]:
        """Return the OpenAPI security definition for API keys."""
        return {
            "type": "apiKey",
            "in": "header",
            "name": "Authorization",
            "description": (
                "Long-lived machine credentials for services the user "
                "runs themselves -- the transaction importers, scripts, "
                "self-hosted integrations.\n\n"
                "Send as `Authorization: Api-Key <key>`. Keys are "
                "minted at `/api/v1/users/me/api-keys/`, which returns "
                "the plaintext exactly once (only a hash is stored), "
                "and are revoked there too. A key may carry an expiry; "
                "its owner is emailed before it lapses.\n\n"
                "API keys are machine credentials: they reach the "
                "budgeting domain but are refused on user/security "
                "endpoints. Use OAuth2 instead when a 3rd party -- not "
                "the user -- will hold the credential."
            ),
        }
