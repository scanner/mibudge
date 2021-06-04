from django.apps import AppConfig


class MoneyPoolsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "mibudge.moneypools"

    ####################################################################
    #
    def ready(self):
        # Need to import the signals module so that our @receiver
        # handlers get properly registered.
        #
        from .signals import transaction_pre_save
