"""
DRF authentication for API keys.

API keys are long-lived machine credentials (see users.models.APIKey)
sent as ``Authorization: Api-Key <key>``.  They authenticate as the
key's owning user; ``request.auth`` is set to the APIKey instance,
which is how the RequiresInteractiveAuth permission distinguishes
machine credentials from interactive JWT sessions.
"""

# system imports
import logging

# 3rd party imports
from django.utils import timezone
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.authentication import (
    BaseAuthentication,
    get_authorization_header,
)
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

# Project imports
from users.models import APIKey, User

logger = logging.getLogger("users.authentication")


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
class ApiKeyAuthenticationScheme(OpenApiAuthenticationExtension):
    """drf-spectacular security scheme for ApiKeyAuthentication."""

    target_class = "users.authentication.ApiKeyAuthentication"
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
                "API-key authentication. Format: ``Api-Key <key>``."
            ),
        }
