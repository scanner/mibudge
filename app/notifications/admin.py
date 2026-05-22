#!/usr/bin/env python
#
"""Django admin registrations for the notifications app."""

# 3rd party imports
#
from django.contrib import admin

# Project imports
#
from notifications.models import (
    ChannelPreference,
    Notification,
    NotificationLog,
    NotificationPreference,
)


########################################################################
########################################################################
#
@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "user",
        "kind",
        "priority",
        "channel",
        "locale",
        "created_at",
        "log_entry",
    ]
    list_filter = ["channel", "priority", "kind"]
    search_fields = ["user__email", "user__username", "kind"]
    readonly_fields = ["id", "pkid", "created_at", "log_entry"]
    ordering = ["-created_at"]


########################################################################
########################################################################
#
@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "channel", "status", "sent_at", "created_at"]
    list_filter = ["channel", "status"]
    search_fields = ["user__email", "user__username"]
    readonly_fields = ["id", "pkid", "created_at"]
    ordering = ["-created_at"]


########################################################################
########################################################################
#
@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ["user", "kind", "enabled"]
    list_filter = ["enabled", "kind"]
    search_fields = ["user__email", "user__username", "kind"]


########################################################################
########################################################################
#
@admin.register(ChannelPreference)
class ChannelPreferenceAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "channel",
        "digest_frequency",
        "last_digest_sent_at",
    ]
    list_filter = ["channel", "digest_frequency"]
    search_fields = ["user__email", "user__username"]
