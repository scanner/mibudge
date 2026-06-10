#!/usr/bin/env python
#
"""
Admin-initiated user invitation service.

Handles the full lifecycle of a UserInvitation:
  - Creating the invitation and sending the outbound email to the invitee.
  - Cancelling a pending invitation (admin changes their mind).
  - Resending the invitation email for a pending invitation.
  - Accepting an invitation (activates the account; triggers allauth
    password-reset so the new user can set their first password).

Rate-limiting design
--------------------
Two complementary limits prevent invitation abuse:

  Per-invitation resend limit: a single invitation may be resent at most
  ``settings.INVITATION_MAX_RESENDS`` times, no more than once every
  ``settings.INVITATION_RESEND_COOLDOWN_HOURS`` hours.  When the resend
  limit is reached the admin is told to cancel and re-invite; the error
  message includes how many new invitations remain in the rolling window.

  Per-address window limit: no more than ``settings.INVITATION_MAX_PER_WINDOW``
  invitations (of any status) may be created for a given email address in
  any ``settings.INVITATION_WINDOW_DAYS``-day rolling window.  This prevents
  the cancel-and-re-invite path from being used to bypass the resend limit.

URL name constant
-----------------
``INVITATION_URL_NAME`` is the bare (un-namespaced) name registered in
``moneypools/invitation_urls.py``.  It is defined here so that the URL
registration and any ``reverse()`` call reference the same string.
"""

# system imports
#
import logging
from typing import TYPE_CHECKING

# 3rd party imports
#
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

# Project imports
#
from common.invitation import (
    InvitationAlreadyPendingError,
    InvitationError,
    InvitationWindowExceededError,
    ResendCooldownActiveError,
    ResendLimitReachedError,
    TokenAlreadyAcceptedError,
    TokenAlreadyCancelledError,
    TokenExpiredError,
    TokenNotFoundError,
    check_resend,
    record_send,
    send_invitation_email,
    window_count,
)
from users.models import UserInvitation
from users.onboarding import get_or_create_inactive_user, trigger_password_reset

if TYPE_CHECKING:
    from django.http import HttpRequest

    from users.models import User

logger = logging.getLogger(__name__)

########################################################################
# URL name constant -- kept here so invitation_urls.py and reverse()
# calls both reference the same source of truth.
########################################################################

INVITATION_URL_NAME = "user-invitation"

########################################################################
########################################################################
# Re-export shared exceptions so callers can reference them as
# ``invitation_svc.TokenNotFoundError`` etc. without importing from
# common directly.  App-specific exceptions live here.
########################################################################
########################################################################

__all__ = [
    "InvitationError",
    "InvitationAlreadyPendingError",
    "InvitationWindowExceededError",
    "InviteeAlreadyRegisteredError",
    "TokenNotFoundError",
    "TokenExpiredError",
    "TokenAlreadyAcceptedError",
    "TokenAlreadyCancelledError",
    "ResendLimitReachedError",
    "ResendCooldownActiveError",
    "create_user_invitation",
    "cancel_user_invitation",
    "resend_user_invitation",
    "accept_user_invitation",
    "INVITATION_URL_NAME",
]


class InviteeAlreadyRegisteredError(InvitationError):
    """The invitee email already belongs to an active mibudge account."""


########################################################################
########################################################################
#
def create_user_invitation(
    inviter: "User",
    invitee_email: str,
) -> UserInvitation:
    """Create a pending invitation and send the outbound email.

    Args:
        inviter: The staff user sending the invitation.
        invitee_email: Email address of the person being invited.

    Returns:
        The newly created UserInvitation.

    Raises:
        InviteeAlreadyRegisteredError: If invitee_email belongs to an
            active account.
        InvitationAlreadyPendingError: If a pending, non-expired invitation
            to this email already exists.
        InvitationWindowExceededError: If the rolling-window cap has been
            reached for this email address.
    """
    User = get_user_model()
    invitee_email = invitee_email.strip().lower()

    if User.objects.filter(email=invitee_email, is_active=True).exists():
        raise InviteeAlreadyRegisteredError(
            f"{invitee_email!r} already has an active mibudge account."
        )

    if UserInvitation.objects.filter(
        invitee_email=invitee_email,
        status=UserInvitation.Status.PENDING,
        expires_at__gt=timezone.now(),
    ).exists():
        raise InvitationAlreadyPendingError(
            f"A pending invitation for {invitee_email!r} already exists."
        )

    count = window_count(UserInvitation, invitee_email)
    if count >= settings.INVITATION_MAX_PER_WINDOW:
        raise InvitationWindowExceededError(
            f"Too many invitations to {invitee_email!r} in the past "
            f"{settings.INVITATION_WINDOW_DAYS} days "
            f"({count} of {settings.INVITATION_MAX_PER_WINDOW})."
        )

    invitee_user, _created = get_or_create_inactive_user(invitee_email)
    invitation = UserInvitation.make(
        invited_by=inviter,
        invitee_email=invitee_email,
        invitee_user=invitee_user,
    )
    _send_invitation_email(invitation)
    return invitation


####################################################################
#
def cancel_user_invitation(invitation: UserInvitation) -> None:
    """Cancel a pending invitation.

    Args:
        invitation: The invitation to cancel.

    Raises:
        TokenAlreadyCancelledError: If already cancelled.
        TokenAlreadyAcceptedError: If already accepted.
        TokenExpiredError: If already expired.
    """
    _validate_pending(invitation)
    invitation.status = UserInvitation.Status.CANCELLED
    invitation.cancelled_at = timezone.now()
    invitation.save(update_fields=["status", "cancelled_at", "modified_at"])


####################################################################
#
def resend_user_invitation(invitation: UserInvitation) -> None:
    """Resend the invitation email for an existing pending invitation.

    Args:
        invitation: The pending invitation to resend.

    Raises:
        TokenExpiredError, TokenAlreadyAcceptedError,
        TokenAlreadyCancelledError: If the invitation is not pending.
        ResendLimitReachedError: If the per-invitation resend cap has
            been reached.  The error message includes remaining window
            capacity so the admin can decide whether cancelling and
            re-inviting is worthwhile.
        ResendCooldownActiveError: If not enough time has passed since
            the last send.
    """
    _validate_pending(invitation)
    count = window_count(UserInvitation, invitation.invitee_email)
    check_resend(invitation, count)
    record_send(invitation)
    _send_invitation_email(invitation)


####################################################################
#
def accept_user_invitation(
    token: str,
    request: "HttpRequest | None" = None,
) -> UserInvitation:
    """Accept an invitation, activating the invitee's account.

    Triggers an allauth password-reset email so the new user can set
    their first password.

    Args:
        token: The invitation token from the acceptance URL.
        request: Optional HttpRequest, forwarded to allauth for building
            the password-reset link URL.

    Returns:
        The accepted UserInvitation.

    Raises:
        TokenNotFoundError, TokenExpiredError, TokenAlreadyAcceptedError,
        TokenAlreadyCancelledError.
    """
    invitation = _get_or_raise(token)
    _validate_pending(invitation)

    invitee_user = invitation.invitee_user
    if invitee_user is not None and not invitee_user.is_active:
        invitee_user.is_active = True
        invitee_user.save(update_fields=["is_active"])

    invitation.status = UserInvitation.Status.ACCEPTED
    invitation.accepted_at = timezone.now()
    invitation.save(update_fields=["status", "accepted_at", "modified_at"])

    if invitee_user is not None:
        trigger_password_reset(invitee_user, request=request)

    logger.info(
        "UserInvitation %s accepted: %r",
        invitation.pk,
        invitation.invitee_email,
    )
    return invitation


########################################################################
########################################################################
# Internal helpers
########################################################################
########################################################################
#
def _get_or_raise(token: str) -> UserInvitation:
    """Look up an invitation by token or raise TokenNotFoundError."""
    try:
        return UserInvitation.objects.select_related(
            "invited_by",
            "invitee_user",
        ).get(token=token)
    except UserInvitation.DoesNotExist:
        raise TokenNotFoundError(
            f"No invitation found for token {token!r}."
        ) from None


####################################################################
#
def _validate_pending(invitation: UserInvitation) -> None:
    """Raise an appropriate error if the invitation is not pending.

    Also treats an expired-but-still-pending invitation as expired and
    marks it accordingly before raising.
    """
    S = UserInvitation.Status
    match invitation.status:
        case S.CANCELLED:
            raise TokenAlreadyCancelledError
        case S.ACCEPTED:
            raise TokenAlreadyAcceptedError
        case S.EXPIRED:
            raise TokenExpiredError
        case S.PENDING:
            if invitation.is_expired:
                invitation.status = S.EXPIRED
                invitation.save(update_fields=["status", "modified_at"])
                raise TokenExpiredError


####################################################################
#
def _invitation_url(token: str) -> str:
    """Build the full acceptance page URL for the given token."""
    path = reverse(
        f"invitations:{INVITATION_URL_NAME}", kwargs={"token": token}
    )
    return f"{settings.SITE_URL.rstrip('/')}{path}"


####################################################################
#
def _send_invitation_email(invitation: UserInvitation) -> None:
    """Build context and send the invitation email to the invitee."""
    locale = settings.NOTIFICATIONS_DEFAULT_LOCALE
    inviter = invitation.invited_by

    inviter_name = (
        (getattr(inviter, "name", None) or getattr(inviter, "email", "") or "")
        if inviter
        else settings.SITE_DISPLAY_NAME
    )

    context = {
        "invitation_url": _invitation_url(invitation.token),
        "inviter_name": inviter_name,
        "invitee_email": invitation.invitee_email,
        "expires_at": invitation.expires_at,
        "expiry_days": settings.INVITATION_EXPIRY_DAYS,
        "site_url": settings.SITE_URL.rstrip("/"),
        "site_display_name": settings.SITE_DISPLAY_NAME,
        "support_email": settings.SUPPORT_EMAIL,
    }
    send_invitation_email(
        invitation.invitee_email,
        "emails/users/user_invitation",
        context,
        locale,
    )
