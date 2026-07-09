#!/usr/bin/env python
#
"""Celery tasks for the users app."""

# system imports
import logging
from datetime import timedelta
from zoneinfo import ZoneInfo

# 3rd party imports
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.dateformat import format as django_date_format

# Project imports
from config import celery_app
from notifications.service import notify
from users.models import APIKey
from users.notification_kinds import API_KEY_EXPIRING

logger = logging.getLogger("users.tasks")

User = get_user_model()


########################################################################
########################################################################
#
@celery_app.task()
def get_users_count():
    """A pointless Celery task to demonstrate usage."""
    return User.objects.count()


########################################################################
########################################################################
#
@celery_app.task(ignore_result=True)
def notify_expiring_api_keys() -> None:
    """
    Notify owners of API keys that expire soon.

    Runs daily (registered in MANAGED_PERIODIC_TASKS).  Selects active
    keys whose expiry falls within the next
    settings.API_KEY_EXPIRY_NOTICE_DAYS days and sends the owner a
    'users.api_key_expiring' notification, giving them time to mint a
    replacement key.  Each key is warned about exactly once:
    expiry_notified_at records the send, and keys already past expiry,
    revoked, or non-expiring are never selected.
    """
    now = timezone.now()
    cutoff = now + timedelta(days=settings.API_KEY_EXPIRY_NOTICE_DAYS)
    expiring = APIKey.objects.filter(
        revoked_at__isnull=True,
        expiry_notified_at__isnull=True,
        expires_at__gt=now,
        expires_at__lte=cutoff,
    ).select_related("user")

    notified = 0
    for api_key in expiring:
        expires_at = api_key.expires_at
        if expires_at is None:
            # Excluded by the queryset filter; the check narrows the
            # type for mypy.
            continue
        expires_local = expires_at.astimezone(ZoneInfo(api_key.user.timezone))
        notify(
            api_key.user,
            API_KEY_EXPIRING,
            {
                "key_name": api_key.name,
                "key_prefix": api_key.prefix,
                # Django date-format tokens (same as |date filter).
                "expires_at": django_date_format(
                    expires_local, r"N j, Y \a\t g:i A e"
                ),
                "days_left": (expires_at - now).days,
            },
        )
        api_key.expiry_notified_at = now
        api_key.save(update_fields=["expiry_notified_at", "modified_at"])
        notified += 1
        logger.info(
            "notify_expiring_api_keys: warned %s about key %r (%s...) "
            "expiring %s.",
            api_key.user.email,
            api_key.name,
            api_key.prefix,
            expires_at,
        )

    if notified:
        logger.info(
            "notify_expiring_api_keys: %d expiring key(s) notified.",
            notified,
        )
