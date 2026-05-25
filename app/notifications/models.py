#!/usr/bin/env python
#
"""
Notification models.

Notification           -- one pending or delivered notification item per user.
NotificationLog        -- one dispatch record (immediate or digest batch).
NotificationPreference -- per-user per-kind opt-in/out.
ChannelPreference      -- per-user per-channel delivery settings.
"""

# system imports
#
import uuid

# 3rd party imports
#
from django.conf import settings
from django.db import models


########################################################################
########################################################################
#
def get_default_locale() -> str:
    """Return the default notification locale from settings.

    Used as a callable default so the field value stays in sync with
    NOTIFICATIONS_DEFAULT_LOCALE without baking a literal into migrations.
    """
    return settings.NOTIFICATIONS_DEFAULT_LOCALE


########################################################################
########################################################################
#
class NotificationPriority(models.IntegerChoices):
    CRITICAL = 1, "Critical"
    HIGH = 2, "High"
    NORMAL = 3, "Normal"
    LOW = 4, "Low"


########################################################################
########################################################################
#
class Channel(models.TextChoices):
    EMAIL = "email", "Email"
    PUSH = "push", "Push"


########################################################################
########################################################################
#
class DigestFrequency(models.TextChoices):
    """
    How often a user wants to receive their notification digest.

    Daily/twice-daily options fire in the morning window (~7 am local
    time) and/or the evening window (~6 pm local time).  Weekly options
    fire on the chosen day in the morning window.
    """

    DAILY_MORNING = "daily_morning", "Once daily (morning, ~7 am)"
    DAILY_EVENING = "daily_evening", "Once daily (evening, ~6 pm)"
    TWICE_DAILY = "twice_daily", "Twice daily (morning + evening)"
    WEEKLY_FRIDAY = "weekly_friday", "Weekly on Friday"
    WEEKLY_SATURDAY = "weekly_saturday", "Weekly on Saturday"
    WEEKLY_SUNDAY = "weekly_sunday", "Weekly on Sunday"


########################################################################
########################################################################
#
class NotificationStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SENT = "sent", "Sent"
    FAILED = "failed", "Failed"


########################################################################
########################################################################
#
class NotificationLog(models.Model):
    """
    Log record for a single dispatch: one email that may contain one
    or more Notification items (digest batching).  Created by the
    channel layer at send time.

    Notification rows point back here (via log_entry) once dispatched.
    """

    pkid = models.BigAutoField(primary_key=True, editable=False)
    id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_logs",
    )
    channel = models.CharField(max_length=20, choices=Channel)
    sent_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=NotificationStatus,
        default=NotificationStatus.PENDING,
    )
    # Error message populated when status=FAILED.
    error_detail = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]


########################################################################
########################################################################
#
class Notification(models.Model):
    """
    A single notification event queued for a user.

    log_entry is null while the notification is pending.  When the
    channel layer dispatches it (directly or as part of a digest batch),
    log_entry is set to the corresponding NotificationLog row.
    """

    pkid = models.BigAutoField(primary_key=True, editable=False)
    id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    # Dotted kind string, e.g. "moneypools.funding_complete".
    kind = models.CharField(max_length=200)
    priority = models.IntegerField(choices=NotificationPriority)
    # Free-form context dict rendered into the notification template.
    context = models.JSONField(default=dict)
    # BCP 47 locale tag, e.g. "en-us".  Template loader falls back to
    # NOTIFICATIONS_DEFAULT_LOCALE when a locale-specific template is absent.
    locale = models.CharField(max_length=20, default=get_default_locale)
    channel = models.CharField(max_length=20, choices=Channel)

    log_entry = models.ForeignKey(
        NotificationLog,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            # Primary lookup for the digest flush task: pending items per user.
            models.Index(
                fields=["user", "channel", "log_entry"],
                name="notif_user_channel_pending_idx",
            ),
            models.Index(fields=["kind"], name="notif_kind_idx"),
        ]


########################################################################
########################################################################
#
class NotificationPreference(models.Model):
    """Per-user opt-in/out for a specific notification kind."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_preferences",
    )
    kind = models.CharField(max_length=200)
    enabled = models.BooleanField(default=True)

    class Meta:
        unique_together = [("user", "kind")]


########################################################################
########################################################################
#
class ChannelPreference(models.Model):
    """Per-user delivery configuration for a notification channel."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="channel_preferences",
    )
    channel = models.CharField(max_length=20, choices=Channel)
    digest_frequency = models.CharField(
        max_length=20,
        choices=DigestFrequency,
        default=DigestFrequency.DAILY_EVENING,
    )
    # Tracks the last digest send time so the flush task avoids
    # double-sending within the same window.
    last_digest_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [("user", "channel")]
