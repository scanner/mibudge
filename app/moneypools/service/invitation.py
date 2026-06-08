#!/usr/bin/env python
#
"""
Bank-account co-ownership invitation service.

Handles the full lifecycle of a BankAccountInvitation:
  - Creating the invitation and sending the outbound email to the invitee.
  - Cancelling a pending invitation (inviter changes their mind).
  - Accepting an invitation (adds the invitee to BankAccount.owners;
    triggers allauth password-reset for brand-new users).
  - Declining an invitation.

Dual-path design (Django template view + DRF API endpoint)
----------------------------------------------------------
The acceptance / decline pages are served as Django template views at
``/invitations/account/{token}/``.  DRF endpoints at
``/api/v1/invitations/{token}/accept/`` and ``.../decline/`` expose the
same operations for API clients.  Both paths call the same service
functions defined here so business logic lives in exactly one place.

URL name constants
------------------
``INVITATION_URL_NAME`` is the bare (un-namespaced) name registered in
``moneypools/invitation_urls.py``.  It is defined here so that both the
URL registration and any ``reverse()`` call references the same string.
"""

# system imports
#
import logging
from typing import TYPE_CHECKING

# 3rd party imports
#
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from notifications.service import notify

# Project imports
#
from moneypools.models import BankAccountInvitation
from moneypools.notification_kinds import (
    CO_OWNER_INVITATION_ACCEPTED,
    CO_OWNER_INVITATION_DECLINED,
)
from users.onboarding import get_or_create_inactive_user, trigger_password_reset

if TYPE_CHECKING:
    from django.http import HttpRequest

    from moneypools.models import BankAccount
    from users.models import User

logger = logging.getLogger(__name__)

########################################################################
# URL name constant -- kept here so invitation_urls.py and reverse()
# calls both reference the same source of truth.
########################################################################

INVITATION_URL_NAME = "account-invitation"

########################################################################
########################################################################
#


class BankAccountInvitationError(Exception):
    """Base for all invitation service errors."""


class InviteeAlreadyOwnerError(BankAccountInvitationError):
    """The invitee is already a co-owner of this account."""


class InvitationAlreadyPendingError(BankAccountInvitationError):
    """A pending invitation to the same email + account already exists."""


class TokenNotFoundError(BankAccountInvitationError):
    """No BankAccountInvitation exists for the given token."""


class TokenExpiredError(BankAccountInvitationError):
    """The invitation token has passed its expiry."""


class TokenAlreadyCancelledError(BankAccountInvitationError):
    """The invitation has already been cancelled by the inviter."""


class TokenAlreadyAcceptedError(BankAccountInvitationError):
    """The invitation has already been accepted."""


class TokenAlreadyDeclinedError(BankAccountInvitationError):
    """The invitation has already been declined."""


########################################################################
########################################################################
#
def create_invitation(
    account: "BankAccount",
    inviter: "User",
    invitee_email: str,
) -> BankAccountInvitation:
    """Create a pending invitation and send the outbound email.

    Args:
        account: The bank account to invite the new owner to.
        inviter: The authenticated user sending the invitation.
        invitee_email: Email address of the person being invited.

    Returns:
        The newly created BankAccountInvitation.

    Raises:
        InviteeAlreadyOwnerError: If invitee_email is already an owner.
        InvitationAlreadyPendingError: If a pending invitation to this
            email + account already exists and has not expired.
    """
    # Normalize email to lowercase for consistent matching.
    invitee_email = invitee_email.strip().lower()

    User = account.owners.model
    if User.objects.filter(email=invitee_email, bankaccount=account).exists():
        raise InviteeAlreadyOwnerError(
            f"{invitee_email!r} is already an owner of this account."
        )

    if BankAccountInvitation.objects.filter(
        bank_account=account,
        invitee_email=invitee_email,
        status=BankAccountInvitation.Status.PENDING,
        expires_at__gt=timezone.now(),
    ).exists():
        raise InvitationAlreadyPendingError(
            f"A pending invitation for {invitee_email!r} already exists."
        )

    invitee_user, _created = get_or_create_inactive_user(invitee_email)

    invitation = BankAccountInvitation.make(
        bank_account=account,
        invited_by=inviter,
        invitee_email=invitee_email,
        invitee_user=invitee_user,
    )
    _send_invitation_email(invitation)
    return invitation


####################################################################
#
def cancel_invitation(invitation: BankAccountInvitation) -> None:
    """Cancel a pending invitation.

    Args:
        invitation: The invitation to cancel.

    Raises:
        TokenAlreadyCancelledError: If already cancelled.
        TokenAlreadyAcceptedError: If already accepted.
        TokenAlreadyDeclinedError: If already declined.
    """
    _validate_pending(invitation)
    invitation.status = BankAccountInvitation.Status.CANCELLED
    invitation.cancelled_at = timezone.now()
    invitation.save(update_fields=["status", "cancelled_at", "modified_at"])


####################################################################
#
def accept_invitation(
    token: str,
    request: "HttpRequest | None" = None,
) -> BankAccountInvitation:
    """Accept an invitation, adding the invitee to the account's owners.

    For brand-new users (no usable password), a password-reset email is
    triggered so they can set their first password.

    Args:
        token: The invitation token from the acceptance URL.
        request: Optional HttpRequest, forwarded to allauth for building
            the password-reset link URL.

    Returns:
        The accepted BankAccountInvitation.

    Raises:
        TokenNotFoundError, TokenExpiredError, TokenAlreadyCancelledError,
        TokenAlreadyAcceptedError, TokenAlreadyDeclinedError.
    """
    invitation = _get_or_raise(token)
    _validate_pending(invitation)

    account = invitation.bank_account
    invitee_user = invitation.invitee_user
    is_new_user = (
        invitee_user is not None and not invitee_user.has_usable_password()
    )

    # Add invitee to owners.
    if invitee_user is not None:
        if not invitee_user.is_active:
            invitee_user.is_active = True
            invitee_user.save(update_fields=["is_active"])
        account.owners.add(invitee_user)

    invitation.status = BankAccountInvitation.Status.ACCEPTED
    invitation.accepted_at = timezone.now()
    invitation.save(update_fields=["status", "accepted_at", "modified_at"])

    if is_new_user and invitee_user is not None:
        trigger_password_reset(invitee_user, request=request)

    if invitation.invited_by is not None:
        _notify_inviter_accepted(invitation)

    logger.info(
        "Invitation %s accepted: %r added to account %s",
        invitation.pk,
        invitation.invitee_email,
        account.pk,
    )
    return invitation


####################################################################
#
def decline_invitation(token: str) -> BankAccountInvitation:
    """Decline an invitation.

    Args:
        token: The invitation token from the acceptance URL.

    Returns:
        The declined BankAccountInvitation.

    Raises:
        TokenNotFoundError, TokenExpiredError, TokenAlreadyCancelledError,
        TokenAlreadyAcceptedError, TokenAlreadyDeclinedError.
    """
    invitation = _get_or_raise(token)
    _validate_pending(invitation)

    invitation.status = BankAccountInvitation.Status.DECLINED
    invitation.declined_at = timezone.now()
    invitation.save(update_fields=["status", "declined_at", "modified_at"])

    if invitation.invited_by is not None:
        _notify_inviter_declined(invitation)

    return invitation


########################################################################
########################################################################
# Internal helpers
########################################################################
########################################################################
#
def _get_or_raise(token: str) -> BankAccountInvitation:
    """Look up an invitation by token or raise TokenNotFoundError."""
    try:
        return BankAccountInvitation.objects.select_related(
            "bank_account",
            "bank_account__bank",
            "invited_by",
            "invitee_user",
        ).get(token=token)
    except BankAccountInvitation.DoesNotExist:
        raise TokenNotFoundError(
            f"No invitation found for token {token!r}."
        ) from None


####################################################################
#
def _validate_pending(invitation: BankAccountInvitation) -> None:
    """Raise an appropriate error if the invitation is not pending.

    Also treats an expired-but-still-pending invitation as expired and
    marks it accordingly before raising.
    """
    S = BankAccountInvitation.Status
    match invitation.status:
        case S.CANCELLED:
            raise TokenAlreadyCancelledError
        case S.ACCEPTED:
            raise TokenAlreadyAcceptedError
        case S.DECLINED:
            raise TokenAlreadyDeclinedError
        case S.EXPIRED:
            raise TokenExpiredError
        case S.PENDING:
            # Wall-clock expiry overrides the stored PENDING status.
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
def _send_invitation_email(invitation: BankAccountInvitation) -> None:
    """Send the direct invitation email to the invitee."""
    locale = settings.NOTIFICATIONS_DEFAULT_LOCALE
    inviter = invitation.invited_by
    account = invitation.bank_account

    inviter_name = (
        (getattr(inviter, "name", None) or getattr(inviter, "email", "") or "")
        if inviter
        else settings.SITE_DISPLAY_NAME
    )

    is_new_user = (
        invitation.invitee_user is not None
        and not invitation.invitee_user.has_usable_password()
    )

    context = {
        "invitation_url": _invitation_url(invitation.token),
        "inviter_name": inviter_name,
        "bank_account_name": account.name,
        "bank_name": account.bank.name,
        "invitee_email": invitation.invitee_email,
        "expires_at": invitation.expires_at,
        "expiry_days": getattr(settings, "INVITATION_EXPIRY_DAYS", 7),
        "is_new_user": is_new_user,
        "site_url": settings.SITE_URL.rstrip("/"),
        "site_display_name": settings.SITE_DISPLAY_NAME,
        "support_email": settings.SUPPORT_EMAIL,
    }

    template_dir = "emails/moneypools/co_owner_invitation"
    subject = render_to_string(
        f"{template_dir}/email_subject.{locale}.txt", context
    ).strip()
    text_body = render_to_string(
        f"{template_dir}/email_body.{locale}.txt", context
    )
    html_body = render_to_string(
        f"{template_dir}/email_body.{locale}.html", context
    )
    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[invitation.invitee_email],
    )
    msg.attach_alternative(html_body, "text/html")
    msg.send()


####################################################################
#
def _notify_inviter_accepted(invitation: BankAccountInvitation) -> None:
    """Notify the inviter that their invitation was accepted."""
    assert invitation.invited_by is not None
    notify(
        invitation.invited_by,
        CO_OWNER_INVITATION_ACCEPTED,
        context={
            "invitee_email": invitation.invitee_email,
            "bank_account_name": invitation.bank_account.name,
            "bank_name": invitation.bank_account.bank.name,
            "site_url": settings.SITE_URL.rstrip("/"),
            "site_display_name": settings.SITE_DISPLAY_NAME,
            "support_email": settings.SUPPORT_EMAIL,
        },
    )


####################################################################
#
def _notify_inviter_declined(invitation: BankAccountInvitation) -> None:
    """Notify the inviter that their invitation was declined."""
    assert invitation.invited_by is not None
    notify(
        invitation.invited_by,
        CO_OWNER_INVITATION_DECLINED,
        context={
            "invitee_email": invitation.invitee_email,
            "bank_account_name": invitation.bank_account.name,
            "bank_name": invitation.bank_account.bank.name,
            "site_url": settings.SITE_URL.rstrip("/"),
            "site_display_name": settings.SITE_DISPLAY_NAME,
            "support_email": settings.SUPPORT_EMAIL,
        },
    )
