#!/usr/bin/env python
#
"""
Email-change service for the users app.

Handles the full lifecycle of a self-service email-address change:
  - Creating the request and sending the two initial emails
  - Confirming the request (new-address verification)
  - Revoking the request (pre- or post-confirmation)

Dual-path design for web and native clients
-------------------------------------------
The confirmation and revocation links embedded in emails point to Django
GET views registered in users/urls.py (e.g.
``/users/email-change/{token}/confirm/``).  Those views process the action
and redirect the browser to an SPA result page -- the right experience for
any client that follows the link in a browser.

Native mobile apps (iOS / Android) can register the production domain
(mibudge.money) as a Universal Link / App Link in their entitlements.
When the app is installed, the OS intercepts the email link and opens the
app instead of a browser.  The app extracts the token from the URL and
calls the corresponding REST endpoint:

  POST /api/v1/users/me/change-email/{token}/confirm/
  POST /api/v1/users/me/change-email/{token}/revoke/

Those endpoints perform the same service-layer calls as the Django views
and return JSON, giving the native app full control over its own success/
error UI.  When the app is not installed the browser fallback handles the
link transparently.

The two paths (Django view + API endpoint) share the same service
functions defined in this module, so the business logic lives in exactly
one place.

URL name constants
------------------
``EMAIL_CHANGE_CONFIRM_URL_NAME`` and ``EMAIL_CHANGE_REVOKE_URL_NAME``
are the bare (un-namespaced) names registered in ``users/urls.py``.
They are defined here so that both the URL registration and the reverse()
calls in this module reference the same string -- change the name in one
place and it is updated everywhere.

SPA redirect paths
------------------
``SPA_EMAIL_CHANGE_*`` are the full SPA paths the Django confirm/revoke
views redirect to after processing.  They are defined here (rather than
in the views) so that any future caller can import them rather than
hardcoding the path strings.
"""

# system imports
#
import logging
from datetime import timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

# 3rd party imports
#
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.dateformat import format as django_date_format
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)

# Project imports
#
from notifications.service import notify
from users.models import EmailChangeRequest
from users.notification_kinds import (
    EMAIL_CHANGE_REQUESTED,
    EMAIL_CHANGE_SECURITY_ALERT,
)

if TYPE_CHECKING:
    from users.models import User

logger = logging.getLogger(__name__)

########################################################################
# URL name constants -- kept here so users/urls.py and reverse() calls
# both reference the same source of truth.
########################################################################

EMAIL_CHANGE_CONFIRM_URL_NAME = "email-change-confirm"
EMAIL_CHANGE_REVOKE_URL_NAME = "email-change-revoke"

########################################################################
# SPA result-page paths.  The Django confirm/revoke views redirect here.
# Include as module-level constants so any future caller can import them
# rather than hardcoding the path strings.
########################################################################

SPA_EMAIL_CHANGE_CONFIRMED = "/app/email-change/confirmed/"
SPA_EMAIL_CHANGE_REVOKED = "/app/email-change/revoked/"
SPA_EMAIL_CHANGE_ERROR = "/app/email-change/error/"


########################################################################
########################################################################
#
class EmailChangeError(Exception):
    """Base for all email-change service errors."""


class EmailAlreadyTakenError(EmailChangeError):
    """The requested new_email is already in use by another account."""


class RevocationWindowOpenError(EmailChangeError):
    """A confirmed request is still within its revocation window."""


class TokenNotFoundError(EmailChangeError):
    """No EmailChangeRequest exists for the given token."""


class TokenExpiredError(EmailChangeError):
    """The verification token has passed its expiry."""


class AlreadyConfirmedError(EmailChangeError):
    """The request has already been confirmed."""


class AlreadyRevokedError(EmailChangeError):
    """The request has already been revoked."""


class RevocationWindowClosedError(EmailChangeError):
    """The 7-day post-confirmation revocation window has closed."""


########################################################################
########################################################################
#
def create_request(user: "User", new_email: str) -> EmailChangeRequest:
    """Create an EmailChangeRequest and fire the two initial emails.

    Args:
        user: The authenticated user requesting the change.
        new_email: The new email address to switch to.

    Returns:
        The newly created EmailChangeRequest.

    Raises:
        EmailAlreadyTakenError: If new_email is already in use.
        RevocationWindowOpenError: If a confirmed request is still in its
            revocation window (lockout to prevent attacker rotation).
    """
    User = get_user_model()
    if (
        User.objects.filter(email__iexact=new_email)
        .exclude(pk=user.pk)
        .exists()
    ):
        raise EmailAlreadyTakenError(new_email)

    if EmailChangeRequest.active_revocation_window(user) is not None:
        raise RevocationWindowOpenError()

    ecr = EmailChangeRequest.make(user, new_email)

    _send_verification_email(ecr)
    _notify_old_address(user, ecr)

    logger.info(
        "email_change: request %s created for user %s (new=%r)",
        ecr.token[:8],
        user.pk,
        new_email,
    )
    return ecr


########################################################################
########################################################################
#
def confirm_request(token: str) -> EmailChangeRequest:
    """Confirm an email-change request via the new-address token.

    Args:
        token: The token from the verification link.

    Returns:
        The confirmed EmailChangeRequest.

    Raises:
        TokenNotFoundError: Token does not exist.
        AlreadyRevokedError: Request was already revoked.
        AlreadyConfirmedError: Request was already confirmed.
        TokenExpiredError: The 24-hour verification window has passed.
        EmailAlreadyTakenError: new_email was claimed by another account
            between request and confirm time.
    """
    ecr = _get_or_raise(token)

    if ecr.is_revoked:
        raise AlreadyRevokedError()
    if ecr.is_confirmed:
        raise AlreadyConfirmedError()
    if ecr.is_expired:
        raise TokenExpiredError()

    User = get_user_model()
    if (
        User.objects.filter(email__iexact=ecr.new_email)
        .exclude(pk=ecr.user_id)
        .exists()
    ):
        raise EmailAlreadyTakenError(ecr.new_email)

    user = ecr.user
    user.email = ecr.new_email
    user.username = ecr.new_email
    user.save(update_fields=["email", "username"])

    ecr.confirm()

    logger.info(
        "email_change: request %s confirmed for user %s (new=%r)",
        ecr.token[:8],
        user.pk,
        ecr.new_email,
    )
    return ecr


########################################################################
########################################################################
#
def revoke_request(token: str) -> EmailChangeRequest:
    """Revoke an email-change request via the 'this wasn't me' link.

    Works both before and after confirmation, provided the revocation
    window has not closed.  On post-confirmation revocation:
      - User.email / User.username are reverted to old_email.
      - All active sessions (JWT refresh tokens) are invalidated.
      - A security alert is sent to both the old and new addresses.

    Args:
        token: The token from the notification email's revoke link.

    Returns:
        The revoked EmailChangeRequest.

    Raises:
        TokenNotFoundError: Token does not exist.
        AlreadyRevokedError: Already revoked.
        RevocationWindowClosedError: Window closed (> 7 days post-confirm).
    """
    ecr = _get_or_raise(token)

    if ecr.is_revoked:
        raise AlreadyRevokedError()
    if not ecr.is_revocable:
        raise RevocationWindowClosedError()

    was_confirmed = ecr.is_confirmed
    user = ecr.user

    ecr.revoke()

    if was_confirmed:
        user.email = ecr.old_email
        user.username = ecr.old_email
        user.save(update_fields=["email", "username"])
        _invalidate_all_sessions(user)

    _send_security_alerts(ecr, was_confirmed=was_confirmed)

    logger.info(
        "email_change: request %s revoked for user %s (was_confirmed=%s)",
        ecr.token[:8],
        user.pk,
        was_confirmed,
    )
    return ecr


########################################################################
########################################################################
#
def _get_or_raise(token: str) -> EmailChangeRequest:
    """Look up a request by token or raise TokenNotFoundError."""
    try:
        return EmailChangeRequest.objects.select_related("user").get(
            token=token
        )
    except EmailChangeRequest.DoesNotExist:
        raise TokenNotFoundError(token) from None


########################################################################
########################################################################
#
def _invalidate_all_sessions(user: "User") -> None:
    """Blacklist every outstanding JWT refresh token for the user.

    After this call, all active access tokens will fail to refresh within
    their remaining lifetime (up to 60 minutes), and no new access tokens
    can be obtained with any existing refresh token.
    """
    tokens = OutstandingToken.objects.filter(user=user)
    for token in tokens:
        BlacklistedToken.objects.get_or_create(token=token)

    logger.info(
        "email_change: invalidated %d session(s) for user %s",
        tokens.count(),
        user.pk,
    )


########################################################################
########################################################################
#
def _confirm_url(token: str) -> str:
    """Full URL for the new-address verification link."""
    return settings.SITE_URL + reverse(
        f"users:{EMAIL_CHANGE_CONFIRM_URL_NAME}", kwargs={"token": token}
    )


########################################################################
########################################################################
#
def _revoke_url(token: str) -> str:
    """Full URL for the 'this wasn't me' revocation link."""
    return settings.SITE_URL + reverse(
        f"users:{EMAIL_CHANGE_REVOKE_URL_NAME}", kwargs={"token": token}
    )


########################################################################
########################################################################
#
def _render_direct_email(
    template_dir: str,
    context: dict,
    locale: str,
) -> tuple[str, str, str]:
    """Render subject, plain-text body, and HTML body for a direct email.

    Follows the same locale-aware file naming used by the notification
    system so templates are consistent and I18N can be added uniformly:

        email_subject.{locale}.txt
        email_body.{locale}.txt
        email_body.{locale}.html

    Args:
        template_dir: Path under ``templates/`` (e.g.
            ``emails/users/email_change_verification``).
        context: Template context dict.
        locale: BCP 47 locale tag (e.g. ``en-us``).

    Returns:
        Tuple of ``(subject, text_body, html_body)``.
    """
    subject = render_to_string(
        f"{template_dir}/email_subject.{locale}.txt", context
    ).strip()
    text_body = render_to_string(
        f"{template_dir}/email_body.{locale}.txt", context
    )
    html_body = render_to_string(
        f"{template_dir}/email_body.{locale}.html", context
    )
    return subject, text_body, html_body


########################################################################
########################################################################
#
def _send_direct_email(
    to_address: str,
    template_dir: str,
    context: dict,
    locale: str,
) -> None:
    """Render and send a direct (non-notification-system) email.

    Used for emails addressed to the *new* email address, which may not
    belong to a registered user and therefore cannot go through the
    notification service's ``notify()`` path.

    Args:
        to_address: Recipient email address.
        template_dir: Path under ``templates/`` for the template set.
        context: Template context dict.
        locale: BCP 47 locale tag used to select the template files.
    """
    subject, text_body, html_body = _render_direct_email(
        template_dir, context, locale
    )
    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to_address],
    )
    msg.attach_alternative(html_body, "text/html")
    msg.send()


########################################################################
########################################################################
#
def _send_verification_email(ecr: EmailChangeRequest) -> None:
    """Send the new-address verification email.

    The locale is taken from the requesting user's preference (falling
    back to NOTIFICATIONS_DEFAULT_LOCALE).  When per-user locale support
    is added, the same field should be used here -- see the related task
    for the I18N language-lock attack mitigation that must accompany that
    change.
    """
    locale = (
        getattr(ecr.user, "locale", None)
        or settings.NOTIFICATIONS_DEFAULT_LOCALE
    )
    _send_direct_email(
        to_address=ecr.new_email,
        template_dir="emails/users/email_change_verification",
        context={
            "confirm_url": _confirm_url(ecr.token),
            "old_email": ecr.old_email,
            "expires_at": ecr.expires_at,
            "expires_hours": settings.EMAIL_CHANGE_TOKEN_EXPIRY_HOURS,
            # Use the requesting user's timezone so the expiry date is
            # meaningful -- the same person controls both the old and
            # new inboxes.
            "user_timezone": ecr.user.timezone,
            "site_url": settings.SITE_URL.rstrip("/"),
            "site_display_name": settings.SITE_DISPLAY_NAME,
            "support_email": settings.SUPPORT_EMAIL,
        },
        locale=locale,
    )


########################################################################
########################################################################
#
def _notify_old_address(user: "User", ecr: EmailChangeRequest) -> None:
    """Notify the old address that a change was requested (includes revoke link).

    The revocation deadline is pre-formatted as a string (not a datetime)
    because notification contexts are JSON-serialized at queue time --
    datetime objects are not JSON-serializable with Django's default
    JSONField encoder.  Pre-formatting also bakes in the correct timezone
    so the stored context is self-contained and renderable without any
    further computation.
    """
    # Latest possible revocation deadline: if the new address confirms at the
    # last possible moment (expires_at), the window closes at expires_at + 7
    # days.  Templates show this as a bound ("no later than ...").
    revoke_by_latest = ecr.expires_at + timedelta(
        days=settings.EMAIL_CHANGE_REVOCATION_DAYS
    )
    user_tz = ZoneInfo(user.timezone)
    revoke_by_latest_local = revoke_by_latest.astimezone(user_tz)
    # Django date-format tokens (same as |date template filter).
    revoke_by_latest_str = django_date_format(
        revoke_by_latest_local, r"N j, Y \a\t g:i A e"
    )
    notify(
        user,
        EMAIL_CHANGE_REQUESTED,
        {
            "new_email": ecr.new_email,
            "revoke_url": _revoke_url(ecr.token),
            "expires_hours": settings.EMAIL_CHANGE_TOKEN_EXPIRY_HOURS,
            "revocation_days": settings.EMAIL_CHANGE_REVOCATION_DAYS,
            "revoke_by_latest": revoke_by_latest_str,
        },
    )


########################################################################
########################################################################
#
def _send_security_alert_to_new_email(ecr: EmailChangeRequest) -> None:
    """Send a security alert to the new (attacker's) address on revocation.

    Uses the requesting user's locale rather than any preference that
    could have been set by an attacker -- see the related I18N task.
    """
    locale = (
        getattr(ecr.user, "locale", None)
        or settings.NOTIFICATIONS_DEFAULT_LOCALE
    )
    _send_direct_email(
        to_address=ecr.new_email,
        template_dir="emails/users/email_change_security_alert",
        context={
            "new_email": ecr.new_email,
            "site_url": settings.SITE_URL.rstrip("/"),
            "site_display_name": settings.SITE_DISPLAY_NAME,
            "support_email": settings.SUPPORT_EMAIL,
        },
        locale=locale,
    )


########################################################################
########################################################################
#
def _send_security_alerts(
    ecr: EmailChangeRequest, *, was_confirmed: bool
) -> None:
    """Send security alert emails to both old and new addresses on revocation."""
    user = ecr.user
    notify(
        user,
        EMAIL_CHANGE_SECURITY_ALERT,
        {
            "old_email": ecr.old_email,
            "new_email": ecr.new_email,
            "was_confirmed": was_confirmed,
        },
    )
    _send_security_alert_to_new_email(ecr)
