#!/usr/bin/env python
#
"""
Notification service.

Public API::

    notify(user, kind, context, priority=None, locale=None)
    notify_for(obj, kind, context, priority=None)

Both functions are fire-and-forget -- they write a Notification row and
dispatch based on delivery mode.  Delivery modes:

    'digest'    -- notification is queued for the periodic digest flush.
    'immediate' -- notification is sent right away.
    'off'       -- notification is suppressed entirely (no row created).

Non-suppressible kinds (can_suppress=False) always use 'immediate'.
CRITICAL priority additionally forces immediate dispatch regardless of
the stored delivery mode.
"""

# system imports
#
import logging
from typing import TYPE_CHECKING, Any

# 3rd party imports
#
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction as db_transaction

# Project imports
#
from notifications.models import (
    Channel,
    DeliveryMode,
    Notification,
    NotificationPreference,
    NotificationPriority,
)
from notifications.registry import registry

if TYPE_CHECKING:
    from users.models import User as UserType

logger = logging.getLogger(__name__)

User = get_user_model()


########################################################################
########################################################################
#
def _effective_delivery_mode(
    user: "UserType",
    kind: str,
) -> str:
    """
    Return the effective DeliveryMode for this user and kind.

    Non-suppressible kinds always return DeliveryMode.IMMEDIATE.
    For suppressible kinds, the stored NotificationPreference takes
    precedence over the registry default_delivery_mode.

    Args:
        user: The recipient user.
        kind: Dotted kind string.

    Returns:
        A DeliveryMode value string ('digest', 'immediate', or 'off').
    """
    kind_info = registry.get(kind)
    if kind_info is None or not kind_info.can_suppress:
        return DeliveryMode.IMMEDIATE

    try:
        pref = NotificationPreference.objects.get(user=user, kind=kind)
        return pref.delivery_mode
    except NotificationPreference.DoesNotExist:
        return kind_info.default_delivery_mode


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

    Checks the kind registry and the user's delivery mode preference before
    creating the Notification row.  If the effective delivery mode is 'off',
    no row is created and None is returned.  If the mode is 'immediate', or
    if the resolved priority is CRITICAL, the notification is sent right away.
    Otherwise it is left pending for the digest flush task.

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
        The created Notification, or None if the delivery mode is 'off'.

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

    delivery_mode = _effective_delivery_mode(user, kind)
    if delivery_mode == DeliveryMode.OFF:
        logger.debug(
            "notify: user %s has delivery_mode=off for kind %r; skipping.",
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

    if (
        delivery_mode == DeliveryMode.IMMEDIATE
        or resolved_priority == NotificationPriority.CRITICAL
    ):
        from notifications.tasks import send_notification_now

        notification_id = str(notification.id)
        db_transaction.on_commit(
            lambda: send_notification_now.delay(notification_id)
        )
        logger.debug(
            "notify: enqueued immediate send for notification %s "
            "(kind=%r, delivery_mode=%r, priority=%s, user=%s)",
            notification.id,
            kind,
            delivery_mode,
            resolved_priority,
            user.pk,
        )

    return notification


########################################################################
########################################################################
#
def notify_for(
    obj: Any,
    kind: str,
    context: dict[str, Any],
    priority: int | None = None,
) -> list[Notification]:
    """
    Fan out notifications to all recipients registered for this kind.

    Looks up the recipients callable registered with the kind and calls
    notify() for each returned user.  Each recipient uses their own
    preferences and locale independently.

    Args:
        obj: The domain object passed to the registered recipients
            callable (e.g. a BankAccount instance).
        kind: Dotted kind string.
        context: Template context dict.
        priority: Optional priority override.

    Returns:
        List of created Notification instances (may be shorter than the
        recipient count if some have opted out).

    Raises:
        ValueError: If the kind is not registered or has no recipients
            callable registered.
    """
    kind_info = registry.get(kind)
    if kind_info is None:
        raise ValueError(
            f"Unknown notification kind: {kind!r}. "
            "Did you register it in AppConfig.ready()?"
        )
    if kind_info.recipients is None:
        raise ValueError(
            f"Notification kind {kind!r} has no recipients callable. "
            "Pass one via registry.register(recipients=...)."
        )

    results = []
    for user in kind_info.recipients(obj):
        notification = notify(user, kind, context, priority=priority)
        if notification is not None:
            results.append(notification)
    return results
