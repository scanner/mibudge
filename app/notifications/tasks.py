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
from django.core.cache import cache

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

# Consecutive-failure tracking for flush_email_digests.
# After _DIGEST_MAX_FAILURES failures the user is skipped until the
# Redis key expires.  On a successful send the key is deleted immediately.
# If Redis is unavailable the counter is inert (cache returns 0) and
# delivery continues -- acceptable degradation.
#
_DIGEST_MAX_FAILURES = 3
_DIGEST_FAILURE_TTL = 3 * 24 * 60 * 60  # 3 days
_DIGEST_FAILURE_KEY = "notif:email_failures:{pk}"


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
@celery_app.task(bind=True, ignore_result=True)
def send_notification_now(self, notification_id: str) -> None:
    """
    Immediately dispatch a single notification via its channel.

    Called for CRITICAL-priority notifications that bypass the digest
    queue.  Silently returns if the notification no longer exists or
    has already been sent.

    On SMTP failure the task retries with exponential backoff up to
    NOTIFICATIONS_SEND_MAX_RETRIES times (default schedule: 5m, 10m,
    20m, 40m).  After all retries are exhausted a hard error is logged
    and the exception propagates.  Because the notification's log_entry
    link is only written on success, a notification that exhausts retries
    here remains pending and will be picked up by the next digest window
    as a fallback.

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

    max_retries = settings.NOTIFICATIONS_SEND_MAX_RETRIES
    base_delay = settings.NOTIFICATIONS_SEND_RETRY_BASE_DELAY

    try:
        EmailChannel().send(notification)
    except Exception as exc:
        attempt = self.request.retries + 1
        if self.request.retries < max_retries:
            delay = base_delay * (2**self.request.retries)
            logger.warning(
                "send_notification_now: attempt %d/%d failed for %s, "
                "retrying in %ds: %r",
                attempt,
                max_retries + 1,
                notification_id,
                delay,
                exc,
            )
            raise self.retry(
                exc=exc, countdown=delay, max_retries=max_retries
            ) from exc
        logger.error(
            "send_notification_now: permanent failure for notification %s "
            "after %d attempts: %r",
            notification_id,
            attempt,
            exc,
        )
        raise exc


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

    Consecutive send failures are tracked in Redis (via Django's cache).
    After _DIGEST_MAX_FAILURES consecutive failures for a user, that user
    is skipped and a hard error is logged.  The counter resets on a
    successful send, or expires automatically after _DIGEST_FAILURE_TTL
    seconds.
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
        failure_key = _DIGEST_FAILURE_KEY.format(pk=user.pk)
        failure_count = cache.get(failure_key, 0)

        if failure_count >= _DIGEST_MAX_FAILURES:
            logger.error(
                "flush_email_digests: skipping %s -- %d consecutive "
                "failures; delivery suspended for %.0fh",
                user.email,
                failure_count,
                _DIGEST_FAILURE_TTL / 3600,
            )
            continue

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
            cache.delete(failure_key)
            pref.last_digest_sent_at = now_utc
            pref.save(update_fields=["last_digest_sent_at"])
        except Exception as exc:
            new_count = failure_count + 1
            cache.set(failure_key, new_count, timeout=_DIGEST_FAILURE_TTL)
            if new_count >= _DIGEST_MAX_FAILURES:
                logger.error(
                    "flush_email_digests: %d consecutive failures for %s; "
                    "suspending delivery for %.0fh: %r",
                    new_count,
                    user.email,
                    _DIGEST_FAILURE_TTL / 3600,
                    exc,
                )
            else:
                logger.warning(
                    "flush_email_digests: failed to send digest to %s "
                    "(%d/%d consecutive): %r",
                    user.email,
                    new_count,
                    _DIGEST_MAX_FAILURES,
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
