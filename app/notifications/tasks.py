#!/usr/bin/env python
#
"""
Celery tasks for the notifications app.

send_notification_now  -- immediate dispatch for CRITICAL notifications.
flush_email_digests    -- periodic: send digest emails to users whose
                          delivery window just opened.
purge_old_notifications -- periodic: delete rows older than
                           NOTIFICATIONS_RETENTION_DAYS.
"""

# system imports
#
import logging
from datetime import UTC, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# 3rd party imports
#
from django.conf import settings
from django.contrib.auth import get_user_model

# Project imports
#
from config import celery_app
from notifications.models import (
    Channel,
    ChannelPreference,
    DigestFrequency,
    Notification,
    NotificationLog,
)

logger = logging.getLogger(__name__)

User = get_user_model()


class _HasTimezone(Protocol):
    timezone: str


class _HasDigestPref(Protocol):
    digest_frequency: str
    last_digest_sent_at: datetime | None


# Local hour (inclusive) that defines each delivery window.  The flush
# task runs every 30 minutes and fires within the matching hour.
#
_MORNING_HOUR = 7
_EVENING_HOUR = 18

# ISO weekday numbers (Monday=0).
#
_FRIDAY = 4
_SATURDAY = 5
_SUNDAY = 6


########################################################################
########################################################################
#
@celery_app.task(ignore_result=True)
def send_notification_now(notification_id: str) -> None:
    """
    Immediately dispatch a single notification via its channel.

    Called for CRITICAL-priority notifications that bypass the digest
    queue.  Silently returns if the notification no longer exists or
    has already been sent.

    Args:
        notification_id: UUID string of the Notification to send.
    """
    from notifications.channels.email import EmailChannel

    try:
        notification = Notification.objects.select_related("user").get(
            id=notification_id
        )
    except Notification.DoesNotExist:
        logger.warning(
            "send_notification_now: Notification %s not found; skipping.",
            notification_id,
        )
        return

    if notification.log_entry_id is not None:
        logger.debug(
            "send_notification_now: %s already dispatched; skipping.",
            notification_id,
        )
        return

    EmailChannel().send(notification)


########################################################################
########################################################################
#
@celery_app.task(ignore_result=True)
def flush_email_digests() -> None:
    """
    Send digest emails to users whose delivery window just opened.

    Runs every 30 minutes (registered in MANAGED_PERIODIC_TASKS).  For
    each user with pending email notifications, checks their
    ChannelPreference digest_frequency against their local time and
    sends a batched digest when the window matches.
    """
    now_utc = datetime.now(tz=UTC)

    pending_user_ids = list(
        Notification.objects.filter(
            channel=Channel.EMAIL,
            log_entry__isnull=True,
        )
        .values_list("user_id", flat=True)
        .distinct()
    )

    if not pending_user_ids:
        return

    from notifications.channels.email import EmailChannel

    channel = EmailChannel()

    for user in User.objects.filter(pk__in=pending_user_ids):
        pref, _ = ChannelPreference.objects.get_or_create(
            user=user,
            channel=Channel.EMAIL,
            defaults={"digest_frequency": DigestFrequency.DAILY_EVENING},
        )

        if not _is_digest_due(user, pref, now_utc):
            continue

        notifications = list(
            Notification.objects.filter(
                user=user,
                channel=Channel.EMAIL,
                log_entry__isnull=True,
            ).order_by("priority", "created_at")
        )

        if not notifications:
            continue

        try:
            channel.send_batch(notifications)
            pref.last_digest_sent_at = now_utc
            pref.save(update_fields=["last_digest_sent_at"])
        except Exception as exc:
            logger.error(
                "flush_email_digests: failed to send digest to %s: %r",
                user.email,
                exc,
            )


########################################################################
########################################################################
#
@celery_app.task(ignore_result=True)
def purge_old_notifications() -> None:
    """
    Delete Notification and NotificationLog rows past their retention age.

    Runs daily (registered in MANAGED_PERIODIC_TASKS).  The retention
    window is set by NOTIFICATIONS_RETENTION_DAYS in settings.

    Notifications are deleted first; then NotificationLog rows that have
    no remaining notifications and are themselves past the cutoff are
    cleaned up.
    """
    cutoff = datetime.now(tz=UTC) - timedelta(
        days=settings.NOTIFICATIONS_RETENTION_DAYS
    )

    deleted_n, _ = Notification.objects.filter(created_at__lt=cutoff).delete()

    # Remove log entries that are old AND have no remaining notifications
    # (notifications within the retention window still reference them).
    deleted_l, _ = NotificationLog.objects.filter(
        created_at__lt=cutoff,
        notifications__isnull=True,
    ).delete()

    logger.info(
        "purge_old_notifications: deleted %d notification(s) and "
        "%d log(s) older than %s.",
        deleted_n,
        deleted_l,
        cutoff.date(),
    )


########################################################################
########################################################################
#
def _is_digest_due(
    user: _HasTimezone,
    pref: _HasDigestPref,
    now_utc: datetime,
) -> bool:
    """
    Return True if the user's digest delivery window is currently open.

    Converts now_utc to the user's local time and checks whether the
    current hour matches the configured DigestFrequency window.  Uses
    last_digest_sent_at to prevent double-sending within the same window.

    Args:
        user: User instance (must have a timezone attribute).
        pref: The user's ChannelPreference for this channel.
        now_utc: Current UTC datetime.

    Returns:
        True if a digest should be sent now.
    """
    try:
        tz = ZoneInfo(user.timezone)
    except (ZoneInfoNotFoundError, KeyError):
        tz = ZoneInfo("UTC")

    local_now = now_utc.astimezone(tz)
    local_hour = local_now.hour
    local_weekday = local_now.weekday()

    in_morning = local_hour == _MORNING_HOUR
    in_evening = local_hour == _EVENING_HOUR

    # Return False if we are outside the delivery window for this frequency.
    # Each case fires only when the pattern matches AND the guard is True
    # (i.e. we are NOT in the right window).  When the guard is False we are
    # in the correct window and fall through to the last-sent check below.
    match pref.digest_frequency:
        case DigestFrequency.DAILY_MORNING if not in_morning:
            return False
        case DigestFrequency.DAILY_EVENING if not in_evening:
            return False
        case DigestFrequency.TWICE_DAILY if not (in_morning or in_evening):
            return False
        case DigestFrequency.WEEKLY_FRIDAY if not (
            local_weekday == _FRIDAY and in_morning
        ):
            return False
        case DigestFrequency.WEEKLY_SATURDAY if not (
            local_weekday == _SATURDAY and in_morning
        ):
            return False
        case DigestFrequency.WEEKLY_SUNDAY if not (
            local_weekday == _SUNDAY and in_morning
        ):
            return False

    # Already sent within this exact hour window today?
    if pref.last_digest_sent_at is not None:
        last_local = pref.last_digest_sent_at.astimezone(tz)
        if (
            last_local.date() == local_now.date()
            and last_local.hour == local_hour
        ):
            return False

    return True
