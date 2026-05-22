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
from dataclasses import dataclass


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
        can_suppress: If False, user preferences cannot disable this
            kind (CRITICAL / security-related notifications).
        default_opt_in: Whether users are subscribed by default.
    """

    kind: str
    display_name: str
    default_priority: int
    can_suppress: bool
    default_opt_in: bool


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
        default_opt_in: bool = True,
    ) -> None:
        """
        Register a notification kind.

        Args:
            kind: Dotted string identifier, e.g. 'moneypools.funding_complete'.
                Must be globally unique.
            display_name: Human-readable label for the preferences UI.
            default_priority: NotificationPriority int value.
            can_suppress: Whether users can opt out of this kind.
            default_opt_in: Whether new users receive this kind by default.

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
            default_opt_in=default_opt_in,
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
