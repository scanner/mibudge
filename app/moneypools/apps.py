from django.apps import AppConfig


class MoneyPoolsConfig(AppConfig):
    name = "moneypools"

    ####################################################################
    #
    def ready(self):
        # Need to import the signals module so that our @receiver
        # handlers get properly registered.
        #
        # Deferred import: notification_kinds imports from notifications.models,
        # which requires the app registry to be fully initialized.  ready() is
        # the correct place for any import that touches Django models.
        from . import (
            notification_kinds,
            signals,  # noqa: F401
        )

        notification_kinds.register_all()
