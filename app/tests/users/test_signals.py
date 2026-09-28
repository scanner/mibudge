#!/usr/bin/env python
#
"""Tests for users.signals."""

# system imports
from unittest.mock import MagicMock, call

# 3rd party imports
import pytest
import pytest_check as check
from allauth.account.signals import (
    email_changed,
    password_changed,
    password_reset,
)
from django.dispatch import Signal
from faker import Faker

# Project imports
from notifications.models import Notification, NotificationPriority
from users.models import User
from users.notification_kinds import EMAIL_CHANGED, PASSWORD_CHANGED

pytestmark = pytest.mark.django_db


########################################################################
########################################################################
#
class TestPasswordChangedSignal:
    """Tests for the password_changed and password_reset signal handlers."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "signal",
        [
            pytest.param(password_changed, id="password-changed"),
            pytest.param(password_reset, id="password-reset"),
        ],
    )
    def test_fires_critical_notification(
        self,
        user: User,
        mock_send_notification_now: MagicMock,
        signal: Signal,
    ) -> None:
        """
        GIVEN: the password_changed allauth signal, or password_reset
               (forgot-password flow), is sent
        WHEN:  the handler runs
        THEN:  a CRITICAL Notification row is created for the user and
               the immediate send task is enqueued
        """
        signal.send(sender=user.__class__, request=None, user=user)

        notification = Notification.objects.get(
            user=user, kind=PASSWORD_CHANGED
        )
        check.equal(
            notification.priority, NotificationPriority.CRITICAL, "critical"
        )
        check.equal(notification.context, {}, "with no context")
        check.equal(
            mock_send_notification_now.delay.call_args_list,
            [call(str(notification.id))],
            "sent immediately",
        )


########################################################################
########################################################################
#
class TestEmailChangedSignal:
    """Tests for the email_changed signal handler."""

    ####################################################################
    #
    def test_fires_critical_notification(
        self,
        user: User,
        mock_send_notification_now: MagicMock,
        faker: Faker,
    ) -> None:
        """
        GIVEN: the email_changed allauth signal is sent
        WHEN:  the handler runs
        THEN:  a CRITICAL Notification row is created for the user with
               from_email and to_email in context, and the immediate
               send task is enqueued
        """
        from_addr = MagicMock(email=faker.unique.email())
        to_addr = MagicMock(email=faker.unique.email())

        email_changed.send(
            sender=user.__class__,
            request=None,
            user=user,
            from_email_address=from_addr,
            to_email_address=to_addr,
        )

        notification = Notification.objects.get(user=user, kind=EMAIL_CHANGED)
        check.equal(
            notification.priority, NotificationPriority.CRITICAL, "critical"
        )
        check.equal(
            notification.context,
            {"from_email": from_addr.email, "to_email": to_addr.email},
            "context carries both addresses and nothing else",
        )
        check.equal(
            mock_send_notification_now.delay.call_args_list,
            [call(str(notification.id))],
            "sent immediately",
        )
