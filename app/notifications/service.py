#!/usr/bin/env python
#
"""
Notification service.

Public API::

    notify(user, kind, context, priority=None, locale=None)
    notify_account_owners(account, kind, context, priority=None)

Both functions are fire-and-forget: they write a Notification row and,
for CRITICAL priority, enqueue a Celery task.  Non-critical notifications
are picked up by the periodic flush_email_digests task.
"""

# system imports
#
import logging
from typing import TYPE_CHECKING, Any

# 3rd party imports
#
from django.conf import settings
from django.contrib.auth import get_user_model

# Project imports
#
from notifications.models import (
    Channel,
    Notification,
    NotificationPreference,
    NotificationPriority,
)
from notifications.registry import registry

if TYPE_CHECKING:
    from moneypools.models import BankAccount
    from users.models import User as UserType

logger = logging.getLogger(__name__)

User = get_user_model()


########################################################################
########################################################################
#
def _get_preference(
    user: "UserType",
    kind: str,
) -> bool:
    """
    Return True if the user has this notification kind enabled.

    Checks NotificationPreference rows first; falls back to the kind's
    default_opt_in from the registry.

    Args:
        user: The recipient user.
        kind: Dotted kind string.

    Returns:
        True if the notification should be sent.
    """
    kind_info = registry.get(kind)
    default = kind_info.default_opt_in if kind_info is not None else True

    try:
        pref = NotificationPreference.objects.get(user=user, kind=kind)
        return pref.enabled
    except NotificationPreference.DoesNotExist:
        return default


########################################################################
########################################################################
#
def notify(
    user: "UserType",
    kind: str,
    context: dict[str, Any],
    priority: int | None = None,
    locale: str | None = None,
) -> Notification | None:
    """
    Queue a notification for delivery to a single user.

    Checks the kind registry and user preferences before creating the
    Notification row.  CRITICAL notifications bypass preferences entirely
    and are enqueued for immediate dispatch.  All others are left pending
    for the digest flush task.

    Args:
        user: Recipient user instance.
        kind: Dotted kind string (must be registered in the registry).
        context: Free-form dict rendered into the notification templates.
        priority: Override the kind's default priority.  Use
            NotificationPriority constants.  If None, uses the registry
            default.
        locale: Override the user's BCP 47 locale (e.g. 'fr-ca').
            Defaults to NOTIFICATIONS_DEFAULT_LOCALE from settings.

    Returns:
        The created Notification, or None if the user has opted out.

    Raises:
        ValueError: If the kind is not registered.
    """
    kind_info = registry.get(kind)
    if kind_info is None:
        raise ValueError(
            f"Unknown notification kind: {kind!r}. "
            "Did you register it in AppConfig.ready()?"
        )

    resolved_priority = (
        priority if priority is not None else kind_info.default_priority
    )
    resolved_locale = locale or settings.NOTIFICATIONS_DEFAULT_LOCALE

    # Non-suppressible kinds always go through regardless of preferences.
    if kind_info.can_suppress:
        if not _get_preference(user, kind):
            logger.debug(
                "notify: user %s has opted out of kind %r; skipping.",
                user.pk,
                kind,
            )
            return None

    notification = Notification.objects.create(
        user=user,
        kind=kind,
        priority=resolved_priority,
        context=context,
        locale=resolved_locale,
        channel=Channel.EMAIL,
    )

    if resolved_priority == NotificationPriority.CRITICAL:
        # Bypass the digest queue -- send immediately via Celery.
        from notifications.tasks import send_notification_now

        send_notification_now.delay(str(notification.id))
        logger.debug(
            "notify: enqueued immediate send for CRITICAL notification %s "
            "(kind=%r, user=%s)",
            notification.id,
            kind,
            user.pk,
        )

    return notification


########################################################################
########################################################################
#
def notify_account_owners(
    account: "BankAccount",
    kind: str,
    context: dict[str, Any],
    priority: int | None = None,
) -> list[Notification]:
    """
    Queue a notification for every owner of a bank account.

    Each owner uses their own preferences and locale independently.
    Joint accounts may have multiple owners, each of whom receives
    their own notification.

    Args:
        account: The BankAccount whose owners should be notified.
        kind: Dotted kind string.
        context: Template context dict.
        priority: Optional priority override.

    Returns:
        List of created Notification instances (may be shorter than the
        owner count if some owners have opted out).
    """
    results = []
    for owner in account.owners.all():
        notification = notify(owner, kind, context, priority=priority)
        if notification is not None:
            results.append(notification)
    return results
