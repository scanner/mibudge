#!/usr/bin/env python
#
"""
Helpers for onboarding new users via invitation flows.

Used by both the bank-account co-ownership flow (moneypools) and the
admin-initiated user invitation flow (users).  Centralising the
inactive-user creation and password-reset trigger here prevents the
two flows from duplicating logic.
"""

# system imports
#
import logging
from typing import TYPE_CHECKING

# 3rd party imports
#
from allauth.account import app_settings as allauth_app_settings
from allauth.account.internal.flows.password_reset import request_password_reset
from django.contrib.auth import get_user_model

if TYPE_CHECKING:
    from django.http import HttpRequest

    from users.models import User

logger = logging.getLogger(__name__)


####################################################################
#
def get_or_create_inactive_user(
    email: str,
) -> tuple["User", bool]:
    """Find or create an inactive User record for the given email.

    The returned user has ``is_active=False`` and no usable password
    (``has_usable_password() == False``).  The email is used as both
    the ``email`` and ``username`` fields, consistent with the project's
    email-as-username convention.

    Returns a (user, created) tuple -- True when a new record was made.
    Callers should activate the user and/or trigger a password reset
    when the invitation is accepted.
    """
    User = get_user_model()
    user, created = User.objects.get_or_create(
        email=email,
        defaults={
            "username": email,
            "is_active": False,
        },
    )
    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    return user, created


####################################################################
#
def trigger_password_reset(
    user: "User",
    request: "HttpRequest | None" = None,
) -> None:
    """Send a password-reset email to *user* via allauth.

    Called when a brand-new (no-password) user accepts an invitation so
    they can set their first password and activate their account.

    Passes *request* through to allauth for URL construction.  When
    ``request`` is ``None`` allauth falls back to
    ``django.contrib.sites`` for the hostname, so both the Django-view
    and API-endpoint call paths work.
    """
    token_generator = allauth_app_settings.PASSWORD_RESET_TOKEN_GENERATOR()
    request_password_reset(
        request=request,
        email=user.email,
        users=[user],
        token_generator=token_generator,
    )
    logger.info(
        "Password-reset email dispatched for new user %r (pk=%s)",
        user.email,
        user.pk,
    )
