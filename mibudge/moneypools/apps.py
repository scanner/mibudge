from django.apps import AppConfig


class MoneyPoolsConfig(AppConfig):
    name = "mibudge.moneypools"

    ####################################################################
    #
    def ready(self):
        # Need to import the signals module so that our @receiver
        # handlers get properly registered.
        #
        from .signals import (  # noqa: F401
            internal_transaction_pre_save,
            transaction_pre_save,
        )
