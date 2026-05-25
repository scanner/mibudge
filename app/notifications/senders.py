#!/usr/bin/env python
#
"""
Notification sender configuration.

A sender represents an outbound identity -- a 'from' address and optional
dedicated SMTP credentials.  Multiple senders allow different notification
types to originate from distinct addresses (e.g. 'notifications@' vs
'support@') without sharing credentials.

Senders are configured via NOTIFICATION_SENDERS in settings.py and
resolved at send time via get_sender().
"""

# system imports
#
from dataclasses import dataclass

# 3rd party imports
#
from django.conf import settings


########################################################################
########################################################################
#
@dataclass(frozen=True)
class SenderConfig:
    """
    Configuration for a single outbound notification sender.

    Args:
        id: Unique string identifier referenced in notify() calls and
            stored on Notification rows for audit.
        display_name: Human-readable name shown in the From header.
        from_email: Full 'From' address, e.g. 'Name <addr@example.com>'.
        smtp_user: SMTP username for per-sender auth.  Empty string means
            use the global Django email backend (no per-sender connection).
        smtp_password: SMTP password paired with smtp_user.
    """

    id: str
    display_name: str
    from_email: str
    smtp_user: str = ""
    smtp_password: str = ""


########################################################################
########################################################################
#
def get_sender(sender_id: str | None = None) -> SenderConfig:
    """
    Return the SenderConfig for the given sender ID.

    An empty string or None resolves to NOTIFICATION_DEFAULT_SENDER.

    Args:
        sender_id: Sender ID string, or '' / None to use the default.

    Returns:
        The matching SenderConfig.

    Raises:
        ValueError: If sender_id (or the default) does not match any
            entry in NOTIFICATION_SENDERS.
    """
    resolved_id = sender_id or settings.NOTIFICATION_DEFAULT_SENDER
    for entry in settings.NOTIFICATION_SENDERS:
        if entry[0] == resolved_id:
            return SenderConfig(*entry)
    raise ValueError(
        f"Unknown notification sender: {resolved_id!r}. "
        "Check NOTIFICATION_SENDERS and NOTIFICATION_DEFAULT_SENDER in settings."
    )
