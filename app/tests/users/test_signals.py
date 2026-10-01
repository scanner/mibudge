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
from rest_framework_simplejwt.tokens import RefreshToken

# Project imports
from notifications.models import Notification, NotificationPriority
from tests.users.session_checks import session_valid
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
        "signal,context",
        [
            pytest.param(password_changed, {}, id="password-changed"),
            pytest.param(
                password_reset,
                {"reset": True, "api_keys": []},
                id="password-reset",
            ),
        ],
    )
    def test_fires_critical_notification(
        self,
        user: User,
        mock_send_notification_now: MagicMock,
        signal: Signal,
        context: dict,
    ) -> None:
        """
        GIVEN: the password_changed allauth signal, or password_reset
               (forgot-password flow), is sent
        WHEN:  the handler runs
        THEN:  a CRITICAL Notification row is created for the user, a
               reset marked as one and listing the (here, no) API keys,
               and the immediate send task is enqueued
        """
        signal.send(sender=user.__class__, request=None, user=user)

        notification = Notification.objects.get(
            user=user, kind=PASSWORD_CHANGED
        )
        check.equal(
            notification.priority, NotificationPriority.CRITICAL, "critical"
        )
        check.equal(notification.context, context, "with its context")
        check.equal(
            mock_send_notification_now.delay.call_args_list,
            [call(str(notification.id))],
            "sent immediately",
        )

    ####################################################################
    #
    @pytest.mark.parametrize(
        "signal",
        [
            pytest.param(password_changed, id="password-changed"),
            pytest.param(password_reset, id="password-reset"),
        ],
    )
    def test_ends_every_session(
        self,
        user: User,
        mock_send_notification_now: MagicMock,
        signal: Signal,
    ) -> None:
        """
        GIVEN: a user signed in on two devices
        WHEN:  a password change (from either change path) or a
               completed reset is signalled
        THEN:  both sessions end
        """
        sessions = [RefreshToken.for_user(user) for _ in range(2)]

        signal.send(sender=user.__class__, request=None, user=user)

        assert [session_valid(s) for s in sessions] == [False, False]


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
