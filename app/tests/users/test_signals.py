#!/usr/bin/env python
#
"""Tests for users.signals."""

from collections.abc import Callable
from unittest.mock import patch

import pytest
from allauth.account.signals import password_changed, password_reset
from notifications.models import Notification, NotificationPriority

from users.notification_kinds import PASSWORD_CHANGED

pytestmark = pytest.mark.django_db


########################################################################
########################################################################
#
class TestPasswordChangedSignal:
    """Tests for the password_changed signal handler."""

    ####################################################################
    #
    def test_fires_critical_notification(
        self,
        user_factory: Callable,
    ):
        """
        GIVEN: the password_changed allauth signal is sent
        WHEN:  the handler runs
        THEN:  a CRITICAL Notification row is created for the user and
               the immediate send task is enqueued
        """
        user = user_factory()

        with patch("notifications.tasks.send_notification_now") as mock_task:
            password_changed.send(
                sender=user.__class__, request=None, user=user
            )

        notification = Notification.objects.get(
            user=user, kind=PASSWORD_CHANGED
        )
        assert notification.priority == NotificationPriority.CRITICAL
        assert "changed_at" in notification.context
        mock_task.delay.assert_called_once_with(str(notification.id))

    ####################################################################
    #
    def test_password_reset_fires_notification(
        self,
        user_factory: Callable,
    ):
        """
        GIVEN: the password_reset allauth signal is sent (forgot-password flow)
        WHEN:  the handler runs
        THEN:  a CRITICAL Notification row is created for the user
        """
        user = user_factory()

        with patch("notifications.tasks.send_notification_now") as mock_task:
            password_reset.send(sender=user.__class__, request=None, user=user)

        notification = Notification.objects.get(
            user=user, kind=PASSWORD_CHANGED
        )
        assert notification.priority == NotificationPriority.CRITICAL
        mock_task.delay.assert_called_once_with(str(notification.id))
