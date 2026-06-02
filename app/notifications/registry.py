#!/usr/bin/env python
#
"""
Notification kind registry.

Each Django app that wants to send notifications registers its kinds
here during AppConfig.ready().  The registry carries the metadata the
service and preferences UI need without the notifications app knowing
anything about the apps that use it.

Usage (in an AppConfig.ready())::

    from notifications.registry import registry
    from notifications.models import NotificationPriority

    registry.register(
        kind="moneypools.funding_complete",
        display_name="Funding cycle complete",
        default_priority=NotificationPriority.NORMAL,
        can_suppress=True,
        default_opt_in=True,
    )
"""

# system imports
#
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any


########################################################################
########################################################################
#
@dataclass(frozen=True)
class KindInfo:
    """
    Metadata for a registered notification kind.

    Attributes:
        kind: Dotted kind string, e.g. 'moneypools.funding_complete'.
        display_name: Human-readable label for the preferences UI.
        default_priority: NotificationPriority int value used when the
            caller does not supply an explicit priority.
        can_suppress: If False, user preferences cannot change this kind
            (security-related notifications).  Delivery mode is always
            'immediate' for non-suppressible kinds.
        default_delivery_mode: DeliveryMode value used when no stored
            preference exists for a user.  Use 'digest', 'immediate', or
            'off'.  Non-suppressible kinds should use 'immediate'.
        recipients: Optional callable used by notify_for().  Receives the
            domain object passed to notify_for() and returns an iterable
            of User instances to notify.
    """

    kind: str
    display_name: str
    default_priority: int
    can_suppress: bool
    default_delivery_mode: str
    recipients: Callable[[Any], Iterable[Any]] | None = field(
        default=None, compare=False, hash=False
    )


########################################################################
########################################################################
#
class NotificationRegistry:
    """Registry of all known notification kinds."""

    ####################################################################
    #
    def __init__(self) -> None:
        self._kinds: dict[str, KindInfo] = {}

    ####################################################################
    #
    def register(
        self,
        kind: str,
        display_name: str,
        default_priority: int,
        can_suppress: bool = True,
        default_delivery_mode: str = "digest",
        recipients: Callable[[Any], Iterable[Any]] | None = None,
    ) -> None:
        """
        Register a notification kind.

        Args:
            kind: Dotted string identifier, e.g. 'moneypools.funding_complete'.
                Must be globally unique.
            display_name: Human-readable label for the preferences UI.
            default_priority: NotificationPriority int value.
            can_suppress: Whether users can change the delivery mode for this
                kind.  Non-suppressible kinds are always delivered immediately.
            default_delivery_mode: DeliveryMode value applied when no stored
                preference exists.  One of 'digest', 'immediate', or 'off'.
            recipients: Optional callable for notify_for() fan-out.  Receives
                the domain object passed to notify_for() and returns an
                iterable of User instances.

        Raises:
            ValueError: If the kind is already registered.
        """
        if kind in self._kinds:
            raise ValueError(
                f"Notification kind {kind!r} is already registered."
            )
        self._kinds[kind] = KindInfo(
            kind=kind,
            display_name=display_name,
            default_priority=default_priority,
            can_suppress=can_suppress,
            default_delivery_mode=default_delivery_mode,
            recipients=recipients,
        )

    ####################################################################
    #
    def get(self, kind: str) -> KindInfo | None:
        """Return KindInfo for the given kind, or None if not registered."""
        return self._kinds.get(kind)

    ####################################################################
    #
    def all(self) -> list[KindInfo]:
        """Return all registered kinds, sorted by kind string."""
        return sorted(self._kinds.values(), key=lambda k: k.kind)

    ####################################################################
    #
    def __contains__(self, kind: str) -> bool:
        return kind in self._kinds


########################################################################
########################################################################
#
registry = NotificationRegistry()
