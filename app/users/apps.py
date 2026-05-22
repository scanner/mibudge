from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class UsersConfig(AppConfig):
    name = "users"
    verbose_name = _("Users")

    def ready(self):
        try:
            import users.signals  # noqa F401
        except ImportError:
            pass
        # Deferred import: notification_kinds imports from notifications.models,
        # which requires the app registry to be fully initialized.  ready() is
        # the correct place for any import that touches Django models.
        from . import notification_kinds

        notification_kinds.register_all()
