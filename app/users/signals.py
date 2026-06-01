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

logger = logging.getLogger(__name__)


########################################################################
########################################################################
#
@receiver(password_changed)
def on_password_changed(sender, request, user, **kwargs) -> None:
    """Fire a CRITICAL notification when a user changes their password."""
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
    """Fire a CRITICAL notification when a user resets their password via email."""
    notify(user, PASSWORD_CHANGED, {})
    logger.debug(
        "password_changed notification queued for user %s (reset)", user.pk
    )
