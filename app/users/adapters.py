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
from urllib.parse import urlsplit, urlunsplit

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.http import HttpRequest


def _rebase_on_site_url(url: str) -> str:
    """Rebase an absolute URL onto SITE_URL's scheme and host.

    SITE_URL is the single source of truth for URLs that leave the
    system in email (the invitation and email-change flows already
    build from it).  Request-derived URLs cannot be trusted for this:
    deployments sit behind proxies that rewrite the Host header to an
    internal name, so the canonical public origin never reaches Django
    as a Host header.

    Args:
        url: An absolute URL as built by allauth.

    Returns:
        The same path/query/fragment on SITE_URL's origin.
    """
    site = urlsplit(settings.SITE_URL)
    parts = urlsplit(url)
    return urlunsplit(
        (site.scheme, site.netloc, parts.path, parts.query, parts.fragment)
    )


class AccountAdapter(DefaultAccountAdapter):
    """Adapter for standard username/password accounts.

    Controls whether new users may register via the signup form, and
    forces allauth's emailed URLs onto the SITE_URL origin.
    """

    def is_open_for_signup(self, request: HttpRequest) -> bool:
        """Return True if self-registration is enabled.

        Reads ACCOUNT_ALLOW_REGISTRATION from settings, which is set via the
        DJANGO_ACCOUNT_ALLOW_REGISTRATION environment variable.
        """
        return getattr(settings, "ACCOUNT_ALLOW_REGISTRATION", False)

    # NOTE: only the password-reset URL needs rebasing.  The other
    # allauth URL builder (get_email_confirmation_url) belongs to the
    # email-verification flow, whose URLs are not mounted in this
    # project (registration is closed; the custom email-change flow
    # builds its links from SITE_URL already).  If that flow is ever
    # enabled, rebase its URLs the same way.
    def get_reset_password_from_key_url(self, key: str) -> str:
        """Return the password-reset-from-key URL on the SITE_URL origin.

        Sent in password-reset emails, including the set-your-first-
        password email new invitees receive on invitation acceptance.

        Args:
            key: The opaque password-reset key.

        Returns:
            Absolute URL rooted at SITE_URL.
        """
        return _rebase_on_site_url(super().get_reset_password_from_key_url(key))


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
