#!/usr/bin/env python
#
"""
Forms for the server-rendered OAuth2 authorization flow.

The only form here is the login form shown at /o/login/.  See
credentials/views.py for why the OAuth2 flow has a login page of its own
rather than reusing the SPA's.
"""

# 3rd party imports
from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import AuthenticationForm


########################################################################
########################################################################
#
class OAuth2LoginForm(AuthenticationForm):
    """Email + password login, matching the SPA's credentials.

    Django's AuthenticationForm authenticates with ``username=``; this
    passes ``email=`` instead so users.backends.EmailBackend handles it,
    which is exactly what the SPA's token endpoint does.  Logging in here
    therefore accepts the same credentials as /app/login/ -- only the
    resulting artifact differs (a Django session instead of a JWT).

    NOTE: allauth's LoginView is deliberately not used.  With
    ACCOUNT_EMAIL_VERIFICATION = 'mandatory' it refuses to log in any
    account without a verified allauth EmailAddress row, and this project
    never creates those -- every login would be rejected.
    """

    username = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(
            attrs={"autofocus": True, "autocomplete": "email"}
        ),
    )

    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "Please enter a correct email address and password.",
    }

    ####################################################################
    #
    def clean(self) -> dict:
        """Authenticate by email, mirroring AuthenticationForm.clean().

        Returns:
            The cleaned data dict.

        Raises:
            ValidationError: If the credentials do not match an account,
                or the account is inactive.
        """
        email = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")

        if email and password:
            self.user_cache = authenticate(
                self.request, email=email, password=password
            )
            if self.user_cache is None:
                raise self.get_invalid_login_error()
            # Rejects inactive users, matching every other credential
            # path (ApiKeyAuthentication, OAuth2Authentication, JWT).
            self.confirm_login_allowed(self.user_cache)

        return self.cleaned_data
