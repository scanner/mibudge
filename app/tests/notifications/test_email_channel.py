#!/usr/bin/env python
#
"""Tests for notifications.channels.email."""

from collections.abc import Callable
from unittest.mock import patch

import pytest
from django.template import TemplateDoesNotExist
from notifications.channels.email import (
    EmailChannel,
    _kind_template_dir,
    _locale_candidates,
    _render_html_with_fallback,
    _render_with_fallback,
)
from notifications.models import (
    NotificationLog,
    NotificationStatus,
)
from pytest_mock import MockerFixture

pytestmark = pytest.mark.django_db


########################################################################
########################################################################
#
class TestLocaleHelpers:
    """Tests for locale utility functions."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "kind,expected",
        [
            (
                "moneypools.funding_complete",
                "notifications/moneypools/funding_complete",
            ),
            ("users.password_changed", "notifications/users/password_changed"),
            ("foo.bar.baz", "notifications/foo/bar/baz"),
        ],
    )
    def test_kind_template_dir(self, kind: str, expected: str) -> None:
        """
        GIVEN: a dotted kind string
        WHEN:  _kind_template_dir() is called
        THEN:  dots are replaced with slashes and 'notifications/' is prepended
        """
        assert _kind_template_dir(kind) == expected

    ####################################################################
    #
    @pytest.mark.parametrize(
        "locale,expected",
        [
            (
                "en-us",
                ["en-us"],
            ),  # same as default: no redundant fallback entry
            (
                "fr-ca",
                ["fr-ca", "en-us"],
            ),  # different: preferred locale first, then default
        ],
    )
    def test_locale_candidates(
        self, locale: str, expected: list[str], settings
    ) -> None:
        """
        GIVEN: a locale that is the same as or different from NOTIFICATIONS_DEFAULT_LOCALE
        WHEN:  _locale_candidates() is called
        THEN:  returns the appropriate candidate list
        """
        settings.NOTIFICATIONS_DEFAULT_LOCALE = "en-us"
        assert _locale_candidates(locale) == expected


########################################################################
########################################################################
#
class TestRenderWithFallback:
    """Tests for _render_with_fallback() and _render_html_with_fallback()."""

    ####################################################################
    #
    def test_falls_back_to_default_locale(self, settings) -> None:
        """
        GIVEN: no template for 'fr-ca' but one exists for the default 'en-us'
        WHEN:  _render_with_fallback() is called with locale='fr-ca'
        THEN:  the en-us template is rendered without error
        """
        settings.NOTIFICATIONS_DEFAULT_LOCALE = "en-us"
        result = _render_with_fallback(
            "moneypools.funding_complete", "email_body", "fr-ca", {}
        )
        assert result.strip() != ""

    ####################################################################
    #
    def test_raises_when_no_template_exists(self, settings) -> None:
        """
        GIVEN: a kind with no templates for either the requested or the default locale
        WHEN:  _render_with_fallback() is called
        THEN:  TemplateDoesNotExist is raised
        """
        settings.NOTIFICATIONS_DEFAULT_LOCALE = "en-us"
        with pytest.raises(TemplateDoesNotExist):
            _render_with_fallback("nonexistent.kind", "email_body", "en-us", {})

    ####################################################################
    #
    def test_html_falls_back_to_default_locale(self, settings) -> None:
        """
        GIVEN: no HTML template for 'fr-ca' but one exists for the default 'en-us'
        WHEN:  _render_html_with_fallback() is called
        THEN:  the en-us HTML template is rendered as fallback
        """
        settings.NOTIFICATIONS_DEFAULT_LOCALE = "en-us"
        result = _render_html_with_fallback(
            "moneypools.funding_complete", "fr-ca", {}
        )
        assert "<" in result  # must be HTML


########################################################################
########################################################################
#
class TestEmailChannelSend:
    """Tests for EmailChannel.send() and EmailChannel.send_batch()."""

    ####################################################################
    #
    def test_send_creates_log_and_links_notification(
        self,
        notification_factory: Callable,
        mailoutbox,
        settings,
    ) -> None:
        """
        GIVEN: a pending Notification
        WHEN:  EmailChannel.send() is called
        THEN:  one email is sent, a SENT NotificationLog row is created,
               and the notification's log_entry points to it
        """
        settings.NOTIFICATIONS_DEFAULT_LOCALE = "en-us"
        notification = notification_factory(log_entry=None)

        EmailChannel().send(notification)

        assert len(mailoutbox) == 1
        assert mailoutbox[0].to == [notification.user.email]

        log = NotificationLog.objects.get(user=notification.user)
        assert log.status == NotificationStatus.SENT
        assert log.sent_at is not None

        notification.refresh_from_db()
        assert notification.log_entry == log

    ####################################################################
    #
    def test_send_batch_sends_one_digest_email(
        self,
        notification_factory: Callable,
        user_factory: Callable,
        mailoutbox,
        settings,
    ) -> None:
        """
        GIVEN: two pending Notifications for the same user
        WHEN:  EmailChannel.send_batch() is called
        THEN:  exactly one digest email is sent and both notifications are linked to the log
        """
        settings.NOTIFICATIONS_DEFAULT_LOCALE = "en-us"
        user = user_factory()
        n1 = notification_factory(user=user, log_entry=None)
        n2 = notification_factory(user=user, log_entry=None)

        EmailChannel().send_batch([n1, n2])

        assert len(mailoutbox) == 1
        assert mailoutbox[0].to == [user.email]

        log = NotificationLog.objects.get(user=user)
        n1.refresh_from_db()
        n2.refresh_from_db()
        assert n1.log_entry == log
        assert n2.log_entry == log

    ####################################################################
    #
    def test_send_failure_marks_log_failed(
        self,
        notification_factory: Callable,
        settings,
    ) -> None:
        """
        GIVEN: a pending Notification and an SMTP layer that raises
        WHEN:  EmailChannel.send() is called
        THEN:  the NotificationLog row is marked FAILED with error_detail set,
               the notification is NOT linked to the log, and the exception propagates
        """
        settings.NOTIFICATIONS_DEFAULT_LOCALE = "en-us"
        notification = notification_factory(log_entry=None)

        with (
            patch(
                "notifications.channels.email.EmailMultiAlternatives.send",
                side_effect=OSError("SMTP connection refused"),
            ),
            pytest.raises(OSError, match="SMTP connection refused"),
        ):
            EmailChannel().send(notification)

        log = NotificationLog.objects.get(user=notification.user)
        assert log.status == NotificationStatus.FAILED
        assert "SMTP connection refused" in log.error_detail

        notification.refresh_from_db()
        assert notification.log_entry is None

    ####################################################################
    #
    def test_from_email_uses_sender_config(
        self,
        notification_factory: Callable,
        mailoutbox,
        settings,
    ) -> None:
        """
        GIVEN: a Notification with a sender_id whose from_email differs from DEFAULT_FROM_EMAIL
        WHEN:  EmailChannel.send() is called
        THEN:  the outbound email uses the sender's from_email, not DEFAULT_FROM_EMAIL
        """
        settings.NOTIFICATIONS_DEFAULT_LOCALE = "en-us"
        settings.NOTIFICATION_SENDERS = [
            ("notifications", "Test", "custom-sender@example.com", "", ""),
        ]
        settings.NOTIFICATION_DEFAULT_SENDER = "notifications"
        notification = notification_factory(log_entry=None, sender_id="")

        EmailChannel().send(notification)

        assert mailoutbox[0].from_email == "custom-sender@example.com"

    ####################################################################
    #
    @pytest.mark.parametrize(
        "debug,expect_connection",
        [
            pytest.param(
                False, True, id="non-debug-opens-per-sender-connection"
            ),
            pytest.param(True, False, id="debug-skips-per-sender-connection"),
        ],
    )
    def test_per_sender_smtp_connection(
        self,
        notification_factory: Callable,
        settings,
        mocker: MockerFixture,
        debug: bool,
        expect_connection: bool,
    ) -> None:
        """
        GIVEN: a sender configured with smtp_user/smtp_password
        WHEN:  EmailChannel.send() is called
        THEN:  get_connection() is called with per-sender credentials when not
               in DEBUG mode, and skipped entirely when DEBUG=True
        """
        settings.NOTIFICATIONS_DEFAULT_LOCALE = "en-us"
        settings.DEBUG = debug
        settings.NOTIFICATION_SENDERS = [
            (
                "smtp-sender",
                "SMTP",
                "smtp@example.com",
                "smtp@example.com",
                "pw",
            ),
        ]
        settings.NOTIFICATION_DEFAULT_SENDER = "smtp-sender"
        notification = notification_factory(
            log_entry=None, sender_id="smtp-sender"
        )

        mock_conn = mocker.MagicMock()
        mock_get_conn = mocker.patch(
            "notifications.channels.email.get_connection",
            return_value=mock_conn,
        )

        EmailChannel().send(notification)

        if expect_connection:
            mock_get_conn.assert_called_once()
            kwargs = mock_get_conn.call_args.kwargs
            assert kwargs["username"] == "smtp@example.com"
            assert kwargs["password"] == "pw"
        else:
            mock_get_conn.assert_not_called()
