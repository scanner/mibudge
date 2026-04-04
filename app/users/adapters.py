"""
Allauth adapter overrides for mibudge.

Adapters are allauth's extension points for customising signup, login, and
social account behaviour without subclassing views. These are registered in
settings via ACCOUNT_ADAPTER and SOCIALACCOUNT_ADAPTER.

Registration is closed by default (DJANGO_ACCOUNT_ALLOW_REGISTRATION=False).
mibudge is intended for small, known user groups -- not open public signup.
Set DJANGO_ACCOUNT_ALLOW_REGISTRATION=True in the environment to enable it.
"""

from typing import Any

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.http import HttpRequest


class AccountAdapter(DefaultAccountAdapter):
    """Adapter for standard username/password accounts.

    Controls whether new users may register via the signup form.
    """

    def is_open_for_signup(self, request: HttpRequest) -> bool:
        """Return True if self-registration is enabled.

        Reads ACCOUNT_ALLOW_REGISTRATION from settings, which is set via the
        DJANGO_ACCOUNT_ALLOW_REGISTRATION environment variable.
        """
        return getattr(settings, "ACCOUNT_ALLOW_REGISTRATION", False)


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """Adapter for OAuth social logins (Google, GitHub, etc.).

    Applies the same registration gate as AccountAdapter so that
    ACCOUNT_ALLOW_REGISTRATION controls both signup paths consistently.
    """

    def is_open_for_signup(
        self, request: HttpRequest, sociallogin: Any
    ) -> bool:
        """Return True if signup via social login is enabled."""
        return getattr(settings, "ACCOUNT_ALLOW_REGISTRATION", False)
