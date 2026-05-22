#!/usr/bin/env python
#
"""AppConfig for the notifications app."""

# 3rd party imports
#
from django.apps import AppConfig


########################################################################
########################################################################
#
class NotificationsConfig(AppConfig):
    name = "notifications"

    ####################################################################
    #
    def ready(self) -> None:
        # Import signals (none yet; placeholder for future use).
        pass
