#!/usr/bin/env python
#
"""
Notification kind constants and registry for the credentials app.

Call register_all() from CredentialsConfig.ready() to make these kinds
available to the notification service.
"""

# 3rd party imports
#
from notifications.models import DeliveryMode, NotificationPriority
from notifications.registry import registry

# Dotted kind strings.
#
API_KEY_EXPIRING = "credentials.api_key_expiring"


########################################################################
########################################################################
#
def register_all() -> None:
    """Register all credentials notification kinds with the registry.

    Called from CredentialsConfig.ready().
    """
    registry.register(
        kind=API_KEY_EXPIRING,
        display_name="API key expiring soon",
        default_priority=NotificationPriority.NORMAL,
        can_suppress=True,
        default_delivery_mode=DeliveryMode.IMMEDIATE,
    )
