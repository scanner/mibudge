#!/usr/bin/env python
#
"""Tests for notifications.channels.email."""

# system imports
from collections.abc import Callable

# 3rd party imports
import pytest
import pytest_check as check
from django.core.mail import EmailMessage
from django.template import TemplateDoesNotExist
from pytest_mock import MockerFixture

# Project imports
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
from users.models import User

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("default_locale"),
]


####################################################################
#
@pytest.fixture
def default_locale(settings) -> None:
    """Pin the fallback locale the templates are looked up under."""
    settings.NOTIFICATIONS_DEFAULT_LOCALE = "en-us"


####################################################################
#
@pytest.fixture
def failing_smtp(mocker: MockerFixture) -> None:
    """Make every outgoing email fail as a refused SMTP connection would."""
    mocker.patch(
        "notifications.channels.email.EmailMultiAlternatives.send",
        side_effect=OSError("SMTP connection refused"),
    )


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
    def test_locale_candidates(self, locale: str, expected: list[str]) -> None:
        """
        GIVEN: a locale that is the same as or different from NOTIFICATIONS_DEFAULT_LOCALE
        WHEN:  _locale_candidates() is called
        THEN:  returns the appropriate candidate list
        """
        assert _locale_candidates(locale) == expected


########################################################################
########################################################################
#
class TestRenderWithFallback:
    """Tests for _render_with_fallback() and _render_html_with_fallback()."""

    ####################################################################
    #
    def test_falls_back_to_default_locale(self) -> None:
        """
        GIVEN: no template for 'fr-ca' but one exists for the default 'en-us'
        WHEN:  _render_with_fallback() is called with locale='fr-ca'
        THEN:  the en-us template is rendered without error
        """
        result = _render_with_fallback(
            "moneypools.funding_complete", "email_body", "fr-ca", {}
        )
        assert result.strip() != ""

    ####################################################################
    #
    def test_raises_when_no_template_exists(self) -> None:
        """
        GIVEN: a kind with no templates for either the requested or the default locale
        WHEN:  _render_with_fallback() is called
        THEN:  TemplateDoesNotExist is raised
        """
        with pytest.raises(TemplateDoesNotExist):
            _render_with_fallback("nonexistent.kind", "email_body", "en-us", {})

    ####################################################################
    #
    def test_html_falls_back_to_default_locale(self) -> None:
        """
        GIVEN: no HTML template for 'fr-ca' but one exists for the default 'en-us'
        WHEN:  _render_html_with_fallback() is called
        THEN:  the en-us HTML template is rendered as fallback
        """
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
        mailoutbox: list[EmailMessage],
    ) -> None:
        """
        GIVEN: a pending Notification
        WHEN:  EmailChannel.send() is called
        THEN:  one email is sent, a SENT NotificationLog row is created,
               and the notification's log_entry points to it
        """
        notification = notification_factory(log_entry=None)

        EmailChannel().send(notification)

        log = NotificationLog.objects.get(user=notification.user)
        notification.refresh_from_db()
        check.equal(
            [m.to for m in mailoutbox],
            [[notification.user.email]],
            "one email, to the user",
        )
        check.equal(log.status, NotificationStatus.SENT, "logged as sent")
        check.is_not_none(log.sent_at, "with a send time")
        check.equal(notification.log_entry, log, "notification linked")

    ####################################################################
    #
    def test_send_batch_sends_one_digest_email(
        self,
        notification_factory: Callable,
        user: User,
        mailoutbox: list[EmailMessage],
    ) -> None:
        """
        GIVEN: two pending Notifications for the same user
        WHEN:  EmailChannel.send_batch() is called
        THEN:  exactly one digest email is sent and both notifications are linked to the log
        """
        n1 = notification_factory(user=user, log_entry=None)
        n2 = notification_factory(user=user, log_entry=None)

        EmailChannel().send_batch([n1, n2])

        log = NotificationLog.objects.get(user=user)
        n1.refresh_from_db()
        n2.refresh_from_db()
        check.equal(
            [m.to for m in mailoutbox], [[user.email]], "one digest email"
        )
        check.equal(n1.log_entry, log, "first notification linked")
        check.equal(n2.log_entry, log, "second notification linked")

    ####################################################################
    #
    def test_send_failure_marks_log_failed(
        self,
        notification_factory: Callable,
        failing_smtp: None,
    ) -> None:
        """
        GIVEN: a pending Notification and an SMTP layer that raises
        WHEN:  EmailChannel.send() is called
        THEN:  the NotificationLog row is marked FAILED with error_detail set,
               the notification is NOT linked to the log, and the exception propagates
        """
        notification = notification_factory(log_entry=None)

        with pytest.raises(OSError, match="SMTP connection refused"):
            EmailChannel().send(notification)

        log = NotificationLog.objects.get(user=notification.user)
        notification.refresh_from_db()
        check.equal(log.status, NotificationStatus.FAILED, "logged as failed")
        check.is_in(
            "SMTP connection refused", log.error_detail, "with the error"
        )
        check.is_none(notification.log_entry, "notification not linked")
