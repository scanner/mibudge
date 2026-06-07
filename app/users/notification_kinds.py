#!/usr/bin/env python
#
"""
Notification kind constants and registry for the users app.

Call register_all() from UsersConfig.ready() to make these kinds
available to the notification service.
"""

# 3rd party imports
#
from notifications.models import DeliveryMode, NotificationPriority
from notifications.registry import registry

# Dotted kind strings.
#
PASSWORD_CHANGED = "users.password_changed"
EMAIL_CHANGED = "users.email_changed"
EMAIL_CHANGE_REQUESTED = "users.email_change_requested"
EMAIL_CHANGE_SECURITY_ALERT = "users.email_change_security_alert"


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
        default_delivery_mode=DeliveryMode.IMMEDIATE,
    )
    registry.register(
        kind=EMAIL_CHANGED,
        display_name="Email address changed",
        default_priority=NotificationPriority.CRITICAL,
        can_suppress=False,
        default_delivery_mode=DeliveryMode.IMMEDIATE,
    )
    registry.register(
        kind=EMAIL_CHANGE_REQUESTED,
        display_name="Email change requested",
        default_priority=NotificationPriority.CRITICAL,
        can_suppress=False,
        default_delivery_mode=DeliveryMode.IMMEDIATE,
    )
    registry.register(
        kind=EMAIL_CHANGE_SECURITY_ALERT,
        display_name="Email change security alert",
        default_priority=NotificationPriority.CRITICAL,
        can_suppress=False,
        default_delivery_mode=DeliveryMode.IMMEDIATE,
    )
