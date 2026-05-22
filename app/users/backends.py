# system imports
#
from typing import Any

# 3rd party imports
#
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import AbstractUser
from django.http import HttpRequest

User = get_user_model()


########################################################################
########################################################################
#
class EmailBackend(ModelBackend):
    """
    Authenticate with email + password.

    The Django admin continues to use the standard ModelBackend (username)
    because AdminAuthenticationForm always passes ``username=``.  This
    backend is called first for the SPA/JWT flow (which passes ``email=``).
    """

    ####################################################################
    #
    def authenticate(  # type: ignore[override]
        self,
        request: HttpRequest | None,
        **kwargs: Any,
    ) -> AbstractUser | None:
        email: str | None = kwargs.get("email")
        password: str | None = kwargs.get("password")
        if email is None or password is None:
            return None
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            # Run the hasher anyway to prevent timing attacks.
            User().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
