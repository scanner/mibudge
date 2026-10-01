"""
Ending a user's sessions and revoking their API keys.

A session is a JWT refresh token; blacklisting it stops it minting new
access tokens, and access tokens already issued run out within
`SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"]`.  API keys are separate
credentials, revoked explicitly.  Callers:

- password change: `end_all_sessions`, then a fresh refresh cookie for
  the request that changed it (`users.api.v1.views`);
- completed password reset: `end_all_sessions`, and the reset
  notification lists `api_key_summaries` for the owner to review
  (`users.signals`);
- email-change revocation: both (`users.email_change`);
- the revoke-all endpoint: `revoke_all_api_keys`.
"""

# system imports
#
import logging
from typing import TYPE_CHECKING

# 3rd party imports
#
from django.db.models import Q, QuerySet
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)

# Project imports
#
from users.models import APIKey

if TYPE_CHECKING:
    from users.models import User

logger = logging.getLogger("users.sessions")


########################################################################
########################################################################
#
def end_all_sessions(user: "User") -> int:
    """
    Blacklist every outstanding refresh token for `user`.

    Args:
        user: The user whose sessions end.

    Returns:
        How many refresh tokens were newly blacklisted.
    """
    tokens = OutstandingToken.objects.filter(user=user).exclude(
        blacklistedtoken__isnull=False
    )
    ended = 0
    for token in tokens:
        _, created = BlacklistedToken.objects.get_or_create(token=token)
        ended += created
    logger.info("Ended %d session(s) for user %s", ended, user.pk)
    return ended


########################################################################
########################################################################
#
def active_api_keys(user: "User") -> QuerySet[APIKey]:
    """Return `user`'s API keys that are neither revoked nor expired."""
    return APIKey.objects.filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()),
        user=user,
        revoked_at__isnull=True,
    )


########################################################################
########################################################################
#
def api_key_summaries(user: "User") -> list[dict[str, str]]:
    """
    Describe `user`'s active API keys for a notification.

    Args:
        user: The user whose API keys are described.

    Returns:
        One dict per active key, newest first: `name`, `prefix`, and
        `created` and `last_used` as ISO dates (`last_used` is
        'never' for an unused key).
    """
    return [
        {
            "name": key.name,
            "prefix": key.prefix,
            "created": key.created_at.date().isoformat(),
            "last_used": (
                key.last_used_at.date().isoformat()
                if key.last_used_at
                else "never"
            ),
        }
        for key in active_api_keys(user)
    ]


########################################################################
########################################################################
#
def revoke_all_api_keys(user: "User") -> int:
    """
    Revoke every active API key `user` holds.

    Args:
        user: The user whose API keys are revoked.

    Returns:
        How many API keys were revoked.
    """
    now = timezone.now()
    revoked = active_api_keys(user).update(revoked_at=now, modified_at=now)
    logger.info("Revoked %d API key(s) for user %s", revoked, user.pk)
    return revoked
