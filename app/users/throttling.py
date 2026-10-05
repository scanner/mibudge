"""
Rate limits for the credential endpoints.

Login is limited per client address (`login`) and per submitted email.
The per-email limit counts every attempt from browsers that have not
signed in to that email before (`login_email`).  A browser that has
carries a device cookie, issued on a successful login, and its attempts
count against a limit of their own (`login_device`), so guessing
against an email cannot lock its owner out of a browser they already
use.  The device cookie is bound to the user's password, so changing
or resetting the password invalidates every device cookie.

Password changes are limited per user (`password_change`) and token
refreshes per client address (`token_refresh`).  Rates live in
`REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']`.
"""

# system imports
#
import hashlib
import secrets
from datetime import timedelta
from typing import Any

# 3rd party imports
#
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.utils.crypto import constant_time_compare, salted_hmac
from rest_framework.exceptions import Throttled
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle

User = get_user_model()

LOGIN_DEVICE_COOKIE_NAME = "login_device"
LOGIN_DEVICE_COOKIE_MAX_AGE = timedelta(days=365)
LOGIN_DEVICE_COOKIE_PATH = "/api/token/"
_DEVICE_SALT = "users.throttling.login_device"

# Attribute caching the device-cookie check on the request: both login
# throttles need it, and it costs a user lookup.
#
_DEVICE_NONCE_ATTR = "_login_device_nonce"


####################################################################
#
def _normalized_email(request: Request) -> str | None:
    """Return the submitted login email, stripped and lowercased."""
    email = request.data.get("email") if hasattr(request.data, "get") else None
    if not isinstance(email, str) or not email.strip():
        return None
    return email.strip().lower()


####################################################################
#
def _password_binding(user: Any) -> str:
    """Return a value that changes whenever `user`'s password does."""
    return salted_hmac(_DEVICE_SALT, user.get_session_auth_hash()).hexdigest()


####################################################################
#
def set_login_device_cookie(response: Response, user: Any) -> None:
    """Mark this browser as one that has signed in to `user`.

    Args:
        response: The successful login response.
        user: The user who signed in.
    """
    value = signing.dumps(
        {
            "u": user.pk,
            "n": secrets.token_urlsafe(16),
            "p": _password_binding(user),
        },
        salt=_DEVICE_SALT,
    )
    response.set_cookie(
        LOGIN_DEVICE_COOKIE_NAME,
        value,
        max_age=int(LOGIN_DEVICE_COOKIE_MAX_AGE.total_seconds()),
        path=LOGIN_DEVICE_COOKIE_PATH,
        httponly=True,
        secure=not settings.DEBUG,
        samesite="Strict",
    )


####################################################################
#
def login_device_nonce(request: Request) -> str | None:
    """Return the device cookie's nonce when it is valid for this login.

    Valid means: signed by us, unexpired, issued to the user whose email
    was submitted, and issued under that user's current password.

    Args:
        request: A login request.

    Returns:
        The cookie's nonce, or None when the cookie is absent or does
        not vouch for this login.
    """
    if hasattr(request, _DEVICE_NONCE_ATTR):
        return getattr(request, _DEVICE_NONCE_ATTR)
    nonce = _check_device_cookie(request)
    setattr(request, _DEVICE_NONCE_ATTR, nonce)
    return nonce


####################################################################
#
def _check_device_cookie(request: Request) -> str | None:
    """Validate the device cookie against the submitted email."""
    raw = request.COOKIES.get(LOGIN_DEVICE_COOKIE_NAME)
    email = _normalized_email(request)
    if not raw or email is None:
        return None
    try:
        payload = signing.loads(
            raw,
            salt=_DEVICE_SALT,
            max_age=LOGIN_DEVICE_COOKIE_MAX_AGE,
        )
    except signing.BadSignature:
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("u"), int):
        return None
    user = User.objects.filter(pk=payload["u"]).first()
    if user is None or user.email.strip().lower() != email:
        return None
    if not constant_time_compare(
        str(payload.get("p", "")), _password_binding(user)
    ):
        return None
    nonce = payload.get("n")
    return nonce if isinstance(nonce, str) else None


########################################################################
########################################################################
#
class LoginThrottled(Throttled):
    """The 429 a throttled login answers, worded for the sign-in form."""

    default_detail = "Too many sign-in attempts."
    extra_detail_singular = "Try again in {wait} second."
    extra_detail_plural = "Try again in {wait} seconds."


########################################################################
########################################################################
#
class LoginRateThrottle(SimpleRateThrottle):
    """Login attempts per client address."""

    scope = "login"

    ####################################################################
    #
    def get_cache_key(self, request: Request, view: Any) -> str | None:
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }


########################################################################
########################################################################
#
class LoginEmailRateThrottle(SimpleRateThrottle):
    """Login attempts per submitted email, from browsers new to it.

    The key is a hash of the normalized email, so no address is stored
    in the cache.  Attempts carrying a valid device cookie are counted
    by `LoginDeviceRateThrottle` instead.
    """

    scope = "login_email"

    ####################################################################
    #
    def get_cache_key(self, request: Request, view: Any) -> str | None:
        email = _normalized_email(request)
        if email is None or login_device_nonce(request) is not None:
            return None
        return self.cache_format % {
            "scope": self.scope,
            "ident": hashlib.sha256(email.encode()).hexdigest(),
        }


########################################################################
########################################################################
#
class LoginDeviceRateThrottle(SimpleRateThrottle):
    """Login attempts per device cookie, from browsers known to the email."""

    scope = "login_device"

    ####################################################################
    #
    def get_cache_key(self, request: Request, view: Any) -> str | None:
        nonce = login_device_nonce(request)
        if nonce is None:
            return None
        return self.cache_format % {"scope": self.scope, "ident": nonce}


########################################################################
########################################################################
#
class PasswordChangeRateThrottle(SimpleRateThrottle):
    """Password-change attempts per authenticated user."""

    scope = "password_change"

    ####################################################################
    #
    def get_cache_key(self, request: Request, view: Any) -> str | None:
        if not request.user or not request.user.is_authenticated:
            return None
        return self.cache_format % {
            "scope": self.scope,
            "ident": request.user.pk,
        }


########################################################################
########################################################################
#
class TokenRefreshRateThrottle(SimpleRateThrottle):
    """Token refreshes per client address."""

    scope = "token_refresh"

    ####################################################################
    #
    def get_cache_key(self, request: Request, view: Any) -> str | None:
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }
