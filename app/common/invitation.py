#!/usr/bin/env python
#
"""
Shared helpers and exceptions for the invitation system.

Used by both the bank-account co-ownership flow (moneypools) and the
admin-initiated user invitation flow (users).

Exception hierarchy
-------------------
``InvitationError`` is the common base.  App-specific exceptions (e.g.
``InviteeAlreadyOwnerError``) inherit from it in their own service module.
All catch sites that need to handle any invitation error can catch
``InvitationError`` (or the narrower ``invitation_svc.InvitationError``
re-exported from the service module).

Rate-limiting helpers
---------------------
``check_resend`` and ``record_send`` implement the per-invitation resend
limits.  The caller is responsible for computing ``window_count`` with the
appropriate scope (email-only for user invitations, account+email for
bank-account invitations) and passing it in.

``window_count`` is a thin query helper that both services use to apply
the rolling-window cap at creation time and to populate the error message
from ``check_resend``.
"""

# system imports
#
import logging
from datetime import timedelta
from typing import Any

# 3rd party imports
#
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger(__name__)

########################################################################
########################################################################
# Shared exceptions
########################################################################
########################################################################
#


class InvitationError(Exception):
    """Base for all invitation service errors."""


class InvitationAlreadyPendingError(InvitationError):
    """A pending invitation to the same target already exists."""


class InvitationWindowExceededError(InvitationError):
    """Too many invitations to this address in the rolling window."""


class TokenNotFoundError(InvitationError):
    """No invitation exists for the given token."""


class TokenExpiredError(InvitationError):
    """The invitation token has passed its expiry."""


class TokenAlreadyAcceptedError(InvitationError):
    """The invitation has already been accepted."""


class TokenAlreadyCancelledError(InvitationError):
    """The invitation has already been cancelled."""


class TokenAlreadyDeclinedError(InvitationError):
    """The invitation has already been declined."""


class ResendLimitReachedError(InvitationError):
    """The per-invitation resend limit has been reached."""


class ResendCooldownActiveError(InvitationError):
    """Not enough time has elapsed since the last send."""


########################################################################
########################################################################
# Shared helpers
########################################################################
########################################################################
#


def window_count(
    model_class: type[Any],
    email: str,
    extra_filters: dict[str, Any] | None = None,
) -> int:
    """Return invitation count for *email* within the rolling window.

    Args:
        model_class: The invitation model to query.
        email: The invitee email address.
        extra_filters: Optional additional filter kwargs (e.g.
            ``{"bank_account": account}`` for account-scoped counting).

    Returns:
        Number of invitations (any status) to *email* in the last
        ``settings.INVITATION_WINDOW_DAYS`` days.
    """
    window_start = timezone.now() - timedelta(
        days=settings.INVITATION_WINDOW_DAYS
    )
    qs = model_class.objects.filter(
        invitee_email=email,
        created_at__gte=window_start,
    )
    if extra_filters:
        qs = qs.filter(**extra_filters)
    return qs.count()


####################################################################
#
def check_resend(invitation: Any, current_window_count: int) -> None:
    """Raise if resend rate limits are exceeded.

    Args:
        invitation: The pending invitation to check.  Must have
            ``send_count`` and ``last_sent_at`` attributes.
        current_window_count: Pre-computed invitation count for the
            rolling window (caller determines the appropriate scope).

    Raises:
        ResendLimitReachedError: ``send_count`` has reached the cap.
            The message includes remaining window capacity.
        ResendCooldownActiveError: Not enough time has passed since
            ``last_sent_at``.
    """
    max_resends = settings.INVITATION_MAX_RESENDS
    if invitation.send_count > max_resends:
        remaining = settings.INVITATION_MAX_PER_WINDOW - current_window_count
        raise ResendLimitReachedError(
            f"Resend limit reached ({max_resends} resends used). "
            f"Cancel and re-invite -- "
            f"{remaining} of {settings.INVITATION_MAX_PER_WINDOW} "
            f"invitations remain in the "
            f"{settings.INVITATION_WINDOW_DAYS}-day window."
        )

    cooldown = timedelta(hours=settings.INVITATION_RESEND_COOLDOWN_HOURS)
    elapsed = timezone.now() - invitation.last_sent_at
    if elapsed < cooldown:
        next_send = invitation.last_sent_at + cooldown
        raise ResendCooldownActiveError(
            f"Please wait until {next_send:%Y-%m-%d %H:%M UTC} before resending."
        )


####################################################################
#
def record_send(invitation: Any) -> None:
    """Increment send_count and update last_sent_at, then save.

    Args:
        invitation: The invitation that was just sent.  Must have
            ``send_count`` and ``last_sent_at`` attributes.
    """
    invitation.send_count += 1
    invitation.last_sent_at = timezone.now()
    invitation.save(update_fields=["send_count", "last_sent_at", "modified_at"])


####################################################################
#
def send_invitation_email(
    to_email: str,
    template_dir: str,
    context: dict[str, Any],
    locale: str,
) -> None:
    """Render and send an invitation email.

    Args:
        to_email: Recipient email address.
        template_dir: Template directory path relative to the template
            root, e.g. ``'emails/users/user_invitation'``.
        context: Template context dict.
        locale: Locale code used to resolve template filenames, e.g.
            ``'en'``.
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
    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to_email],
    )
    msg.attach_alternative(html_body, "text/html")
    msg.send()
    logger.debug("Invitation email sent to %r via %s", to_email, template_dir)
