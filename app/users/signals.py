#!/usr/bin/env python
#
"""Signal handlers for the users app."""

# system imports
#
import logging

# 3rd party imports
#
from allauth.account.signals import password_changed, password_reset
from django.dispatch import receiver
from django.utils import timezone

# Project imports
#
from notifications.service import notify

from users.notification_kinds import PASSWORD_CHANGED

logger = logging.getLogger(__name__)


########################################################################
########################################################################
#
@receiver(password_changed)
def on_password_changed(sender, request, user, **kwargs) -> None:
    """Fire a CRITICAL notification when a user changes their password."""
    notify(
        user,
        PASSWORD_CHANGED,
        {"changed_at": timezone.now().strftime("%Y-%m-%d %H:%M %Z")},
    )
    logger.debug("password_changed notification queued for user %s", user.pk)


########################################################################
########################################################################
#
@receiver(password_reset)
def on_password_reset(sender, request, user, **kwargs) -> None:
    """Fire a CRITICAL notification when a user resets their password via email."""
    notify(
        user,
        PASSWORD_CHANGED,
        {"changed_at": timezone.now().strftime("%Y-%m-%d %H:%M %Z")},
    )
    logger.debug(
        "password_changed notification queued for user %s (reset)", user.pk
    )
