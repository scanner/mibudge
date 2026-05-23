#!/usr/bin/env python
#
"""
Notification kind constants and registry for the users app.

Call register_all() from UsersConfig.ready() to make these kinds
available to the notification service.
"""

# 3rd party imports
#
from notifications.models import NotificationPriority
from notifications.registry import registry

# Dotted kind strings.
#
PASSWORD_CHANGED = "users.password_changed"
EMAIL_CHANGED = "users.email_changed"


########################################################################
########################################################################
#
def register_all() -> None:
    """Register all users notification kinds with the registry.

    Called from UsersConfig.ready().
    """
    registry.register(
        kind=PASSWORD_CHANGED,
        display_name="Password changed",
        default_priority=NotificationPriority.CRITICAL,
        can_suppress=False,
        default_opt_in=True,
    )
    registry.register(
        kind=EMAIL_CHANGED,
        display_name="Email address changed",
        default_priority=NotificationPriority.CRITICAL,
        can_suppress=False,
        default_opt_in=True,
    )
