from django.apps import AppConfig


class MoneyPoolsConfig(AppConfig):
    name = "moneypools"

    ####################################################################
    #
    def ready(self):
        # Need to import the signals module so that our @receiver
        # handlers get properly registered.
        #
        from . import signals  # noqa: F401
