#!/usr/bin/env python
#
"""Signal handlers for the users app."""

# system imports
#
import logging

# 3rd party imports
#
from allauth.account.signals import (
    email_changed,
    password_changed,
    password_reset,
)
from django.dispatch import receiver

# Project imports
#
from notifications.service import notify
from users.notification_kinds import EMAIL_CHANGED, PASSWORD_CHANGED
from users.sessions import api_key_summaries, end_all_sessions

logger = logging.getLogger(__name__)


########################################################################
########################################################################
#
@receiver(password_changed)
def on_password_changed(sender, request, user, **kwargs) -> None:
    """End every session when a user changes their password, and notify.

    Both password-change paths send this signal: the REST endpoint,
    which then sets a fresh refresh cookie so its caller stays signed
    in, and allauth's `/accounts/password/change/` page.
    """
    end_all_sessions(user)
    notify(user, PASSWORD_CHANGED, {})
    logger.debug("password_changed notification queued for user %s", user.pk)


########################################################################
########################################################################
#
@receiver(email_changed)
def on_email_changed(
    sender, request, user, from_email_address, to_email_address, **kwargs
) -> None:
    """Fire a CRITICAL notification when a user changes their email address."""
    notify(
        user,
        EMAIL_CHANGED,
        {
            "from_email": from_email_address.email,
            "to_email": to_email_address.email,
        },
    )
    logger.debug("email_changed notification queued for user %s", user.pk)


########################################################################
########################################################################
#
@receiver(password_reset)
def on_password_reset(sender, request, user, **kwargs) -> None:
    """End every session when a password reset completes, and notify.

    allauth sends `password_reset` only once the new password has been
    set from the emailed link, never when a reset is requested.  The
    notification lists the user's active API keys so the owner can
    revoke any they do not recognise.  An invitee setting their first
    password (`AccountAdapter.set_password` marks it) gets no
    notification.
    """
    end_all_sessions(user)
    if getattr(user, "first_password", False):
        logger.debug("first password set for user %s", user.pk)
        return
    notify(
        user,
        PASSWORD_CHANGED,
        {"reset": True, "api_keys": api_key_summaries(user)},
    )
    logger.debug(
        "password_changed notification queued for user %s (reset)", user.pk
    )
