#!/usr/bin/env python
#
"""Abstract base class for notification channels."""

# system imports
#
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from notifications.models import Notification


########################################################################
########################################################################
#
class BaseChannel(ABC):
    """
    Abstract notification channel.

    Concrete subclasses implement send() for a specific delivery medium
    (email, push, etc.).  The service layer calls send() with a single
    Notification instance; the channel is responsible for rendering the
    appropriate templates and dispatching.
    """

    ####################################################################
    #
    @abstractmethod
    def send(self, notification: "Notification") -> None:
        """
        Render and dispatch a single notification.

        For digest channels (email), callers should use send_batch()
        when dispatching multiple pending notifications together.

        Args:
            notification: A Notification model instance.

        Raises:
            Exception: Any delivery failure; the caller logs and records
                the error on the NotificationLog row.
        """

    ####################################################################
    #
    def send_batch(self, notifications: list["Notification"]) -> None:
        """
        Render and dispatch a batch of notifications as a digest.

        Default implementation sends each individually.  Override in
        channels that support native batching (e.g. email digest).

        Args:
            notifications: List of Notification model instances.
        """
        for notification in notifications:
            self.send(notification)
