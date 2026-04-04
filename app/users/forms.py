from django.contrib.auth import forms as admin_forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

User = get_user_model()


class UserChangeForm(admin_forms.UserChangeForm):
    # django-stubs does not expose inner Meta classes on form types -- revisit if stubs improve
    class Meta(admin_forms.UserChangeForm.Meta):  # type: ignore[name-defined]
        model = User


class UserCreationForm(admin_forms.UserCreationForm):
    # django-stubs does not expose inner Meta classes on form types -- revisit if stubs improve
    class Meta(admin_forms.UserCreationForm.Meta):  # type: ignore[name-defined]
        model = User

        error_messages = {
            "username": {"unique": _("This username has already been taken.")}
        }
