#!/usr/bin/env python
#
"""Tests for notifications.tasks."""

from collections.abc import Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import celery.exceptions
import pytest
from django.core.cache import cache
from freezegun import freeze_time
from notifications.models import (
    Channel,
    ChannelPreference,
    DigestFrequency,
    Notification,
    NotificationLog,
)
from notifications.tasks import (
    _DIGEST_FAILURE_KEY,
    _DIGEST_MAX_FAILURES,
    _is_digest_due,
    flush_email_digests,
    purge_old_notifications,
    send_notification_now,
)

pytestmark = pytest.mark.django_db

# UTC reference datetimes.  User timezone is always "UTC" in these tests
# so local_hour == UTC hour and local_weekday == UTC weekday.
#
# May 21, 2026 = Thursday (weekday 3)
# May 22, 2026 = Friday   (weekday 4)
# May 23, 2026 = Saturday (weekday 5)
# May 24, 2026 = Sunday   (weekday 6)
_THU = datetime(2026, 5, 21, tzinfo=UTC)
_FRI = datetime(2026, 5, 22, tzinfo=UTC)
_SAT = datetime(2026, 5, 23, tzinfo=UTC)
_SUN = datetime(2026, 5, 24, tzinfo=UTC)


def _at(base: datetime, hour: int, minute: int = 0) -> datetime:
    return base.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _make_pref(freq: str, last_sent: datetime | None = None) -> SimpleNamespace:
    return SimpleNamespace(digest_frequency=freq, last_digest_sent_at=last_sent)


def _make_user(tz: str = "UTC") -> SimpleNamespace:
    return SimpleNamespace(timezone=tz)


########################################################################
########################################################################
#
class TestIsDigestDue:
    """Tests for _is_digest_due()."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "freq,now_utc,last_sent_at,expected",
        [
            # DAILY_MORNING fires at local hour 7
            (DigestFrequency.DAILY_MORNING, _at(_THU, 7), None, True),
            (
                DigestFrequency.DAILY_MORNING,
                _at(_THU, 6),
                None,
                False,
            ),  # too early
            (
                DigestFrequency.DAILY_MORNING,
                _at(_THU, 8),
                None,
                False,
            ),  # too late
            (
                DigestFrequency.DAILY_MORNING,
                _at(_THU, 7),
                _at(_THU, 7, 25),
                False,
            ),  # already sent this hour
            # DAILY_EVENING fires at local hour 18
            (DigestFrequency.DAILY_EVENING, _at(_THU, 18), None, True),
            (DigestFrequency.DAILY_EVENING, _at(_THU, 17), None, False),
            (
                DigestFrequency.DAILY_EVENING,
                _at(_THU, 18),
                _at(_THU, 18, 10),
                False,
            ),  # already sent
            # TWICE_DAILY fires at hours 7 and 18
            (DigestFrequency.TWICE_DAILY, _at(_THU, 7), None, True),
            (DigestFrequency.TWICE_DAILY, _at(_THU, 18), None, True),
            (
                DigestFrequency.TWICE_DAILY,
                _at(_THU, 12),
                None,
                False,
            ),  # outside both windows
            # WEEKLY_FRIDAY fires Friday at hour 7 only
            (DigestFrequency.WEEKLY_FRIDAY, _at(_FRI, 7), None, True),
            (
                DigestFrequency.WEEKLY_FRIDAY,
                _at(_THU, 7),
                None,
                False,
            ),  # wrong day
            (
                DigestFrequency.WEEKLY_FRIDAY,
                _at(_FRI, 18),
                None,
                False,
            ),  # wrong hour
            # WEEKLY_SATURDAY fires Saturday at hour 7
            (DigestFrequency.WEEKLY_SATURDAY, _at(_SAT, 7), None, True),
            (
                DigestFrequency.WEEKLY_SATURDAY,
                _at(_FRI, 7),
                None,
                False,
            ),  # wrong day
            # WEEKLY_SUNDAY fires Sunday at hour 7
            (DigestFrequency.WEEKLY_SUNDAY, _at(_SUN, 7), None, True),
            (
                DigestFrequency.WEEKLY_SUNDAY,
                _at(_SAT, 7),
                None,
                False,
            ),  # wrong day
        ],
    )
    def test_is_digest_due(
        self,
        freq: str,
        now_utc: datetime,
        last_sent_at: datetime | None,
        expected: bool,
    ) -> None:
        """
        GIVEN: a digest frequency, current UTC time, and optional last-sent timestamp
        WHEN:  _is_digest_due() is called with user timezone UTC
        THEN:  returns True iff the window is open and the digest has not already been sent
        """
        user = _make_user()
        pref = _make_pref(freq, last_sent=last_sent_at)
        assert _is_digest_due(user, pref, now_utc) == expected

    ####################################################################
    #
    def test_invalid_timezone_falls_back_to_utc(self) -> None:
        """
        GIVEN: a user with a bogus timezone string
        WHEN:  _is_digest_due() is called at 7am UTC with DAILY_MORNING
        THEN:  falls back to UTC and returns True
        """
        user = _make_user(tz="Not/A/Real/Zone")
        pref = _make_pref(DigestFrequency.DAILY_MORNING)
        assert _is_digest_due(user, pref, _at(_THU, 7)) is True


########################################################################
########################################################################
#
class TestSendNotificationNow:
    """Tests for send_notification_now()."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "with_log_entry,expect_send",
        [
            (False, True),  # pending notification -> send() called
            (True, False),  # already dispatched -> send() skipped
        ],
    )
    def test_dispatch_or_skip(
        self,
        with_log_entry: bool,
        expect_send: bool,
        notification_factory: Callable,
        notification_log_factory: Callable,
    ) -> None:
        """
        GIVEN: a notification that is either pending or already dispatched
        WHEN:  send_notification_now() is called
        THEN:  EmailChannel.send() is called iff the notification has no log entry
        """
        log = notification_log_factory() if with_log_entry else None
        notification = notification_factory(log_entry=log)

        with patch("notifications.channels.email.EmailChannel") as mock_cls:
            send_notification_now(str(notification.id))

        if expect_send:
            call_arg = mock_cls.return_value.send.call_args[0][0]
            assert call_arg == notification
        else:
            mock_cls.return_value.send.assert_not_called()

    ####################################################################
    #
    def test_retries_on_transient_failure(
        self,
        notification_factory: Callable,
        settings,
    ) -> None:
        """
        GIVEN: EmailChannel.send raises and retries remain
        WHEN:  send_notification_now() is called for the first time
        THEN:  self.retry() is called with exponential backoff countdown
        """
        settings.NOTIFICATIONS_SEND_MAX_RETRIES = 4
        settings.NOTIFICATIONS_SEND_RETRY_BASE_DELAY = 300

        notification = notification_factory(log_entry=None)

        with patch("notifications.channels.email.EmailChannel") as mock_cls:
            mock_cls.return_value.send.side_effect = OSError("SMTP refused")
            with patch.object(
                send_notification_now,
                "retry",
                side_effect=celery.exceptions.Retry(),
            ) as mock_retry:
                with pytest.raises(celery.exceptions.Retry):
                    send_notification_now(str(notification.id))

        mock_retry.assert_called_once()
        _, kwargs = mock_retry.call_args
        assert kwargs["countdown"] == 300  # base delay, retries=0 -> 300 * 2^0
        assert kwargs["max_retries"] == 4

    ####################################################################
    #
    def test_backoff_doubles_each_retry(
        self,
        notification_factory: Callable,
        settings,
    ) -> None:
        """
        GIVEN: EmailChannel.send raises and this is the second retry attempt
        WHEN:  send_notification_now() is called with retries=1 in the request
        THEN:  countdown is base_delay * 2 (second step of exponential backoff)
        """
        settings.NOTIFICATIONS_SEND_MAX_RETRIES = 4
        settings.NOTIFICATIONS_SEND_RETRY_BASE_DELAY = 300

        notification = notification_factory(log_entry=None)

        send_notification_now.push_request(retries=1)
        try:
            with patch("notifications.channels.email.EmailChannel") as mock_cls:
                mock_cls.return_value.send.side_effect = OSError("SMTP refused")
                with patch.object(
                    send_notification_now,
                    "retry",
                    side_effect=celery.exceptions.Retry(),
                ) as mock_retry:
                    with pytest.raises(celery.exceptions.Retry):
                        send_notification_now(str(notification.id))

            _, kwargs = mock_retry.call_args
            assert kwargs["countdown"] == 600  # 300 * 2^1
        finally:
            send_notification_now.pop_request()

    ####################################################################
    #
    def test_permanent_failure_after_max_retries(
        self,
        notification_factory: Callable,
        settings,
    ) -> None:
        """
        GIVEN: EmailChannel.send raises and all retries are exhausted
        WHEN:  send_notification_now() is called with retries == max_retries
        THEN:  the original exception propagates (no further Retry raised)
        """
        settings.NOTIFICATIONS_SEND_MAX_RETRIES = 4
        settings.NOTIFICATIONS_SEND_RETRY_BASE_DELAY = 300

        notification = notification_factory(log_entry=None)

        send_notification_now.push_request(retries=4)
        try:
            with patch("notifications.channels.email.EmailChannel") as mock_cls:
                mock_cls.return_value.send.side_effect = OSError("SMTP refused")
                with pytest.raises(OSError, match="SMTP refused"):
                    send_notification_now(str(notification.id))
        finally:
            send_notification_now.pop_request()


########################################################################
########################################################################
#
class TestFlushEmailDigests:
    """Tests for flush_email_digests()."""

    ####################################################################
    #
    def test_no_pending_notifications(self) -> None:
        """
        GIVEN: no pending email Notifications in the DB
        WHEN:  flush_email_digests() is called
        THEN:  EmailChannel is never instantiated
        """
        with patch("notifications.channels.email.EmailChannel") as mock_cls:
            flush_email_digests()

        mock_cls.assert_not_called()

    ####################################################################
    #
    @pytest.mark.parametrize(
        "is_due,expect_sent",
        [(True, True), (False, False)],
    )
    def test_respects_digest_window(
        self,
        is_due: bool,
        expect_sent: bool,
        notification_factory: Callable,
        user_factory: Callable,
    ) -> None:
        """
        GIVEN: a user with pending notifications and a configurable digest-due result
        WHEN:  flush_email_digests() is called
        THEN:  send_batch() is called (and pref updated) iff the digest window is open
        """
        user = user_factory(timezone="UTC")
        n1 = notification_factory(user=user, log_entry=None)
        n2 = notification_factory(user=user, log_entry=None)

        with (
            patch("notifications.tasks._is_digest_due", return_value=is_due),
            patch("notifications.channels.email.EmailChannel") as mock_cls,
        ):
            flush_email_digests()

        if expect_sent:
            mock_cls.return_value.send_batch.assert_called_once()
            sent_ids = {
                n.pk for n in mock_cls.return_value.send_batch.call_args[0][0]
            }
            assert sent_ids == {n1.pk, n2.pk}
            pref = ChannelPreference.objects.get(
                user=user, channel=Channel.EMAIL
            )
            assert pref.last_digest_sent_at is not None
        else:
            mock_cls.return_value.send_batch.assert_not_called()

    ####################################################################
    #
    def test_increments_failure_counter_on_send_error(
        self,
        notification_factory: Callable,
        user_factory: Callable,
    ) -> None:
        """
        GIVEN: send_batch raises on the first attempt
        WHEN:  flush_email_digests() is called
        THEN:  the failure counter for that user is incremented to 1
        """
        user = user_factory(timezone="UTC")
        notification_factory(user=user, log_entry=None)

        with (
            patch("notifications.tasks._is_digest_due", return_value=True),
            patch("notifications.channels.email.EmailChannel") as mock_cls,
        ):
            mock_cls.return_value.send_batch.side_effect = OSError("SMTP down")
            flush_email_digests()

        assert cache.get(_DIGEST_FAILURE_KEY.format(pk=user.pk)) == 1

    ####################################################################
    #
    def test_suspends_delivery_after_max_failures(
        self,
        notification_factory: Callable,
        user_factory: Callable,
    ) -> None:
        """
        GIVEN: the user's failure counter is already at _DIGEST_MAX_FAILURES
        WHEN:  flush_email_digests() is called
        THEN:  send_batch is not called for that user
        """
        user = user_factory(timezone="UTC")
        notification_factory(user=user, log_entry=None)
        cache.set(_DIGEST_FAILURE_KEY.format(pk=user.pk), _DIGEST_MAX_FAILURES)

        with (
            patch("notifications.tasks._is_digest_due", return_value=True),
            patch("notifications.channels.email.EmailChannel") as mock_cls,
        ):
            flush_email_digests()

        mock_cls.return_value.send_batch.assert_not_called()

    ####################################################################
    #
    def test_clears_failure_counter_on_success(
        self,
        notification_factory: Callable,
        user_factory: Callable,
    ) -> None:
        """
        GIVEN: the user has a non-zero failure counter and send_batch succeeds
        WHEN:  flush_email_digests() is called
        THEN:  the failure counter is removed from cache
        """
        user = user_factory(timezone="UTC")
        notification_factory(user=user, log_entry=None)
        failure_key = _DIGEST_FAILURE_KEY.format(pk=user.pk)
        cache.set(failure_key, 2)

        with (
            patch("notifications.tasks._is_digest_due", return_value=True),
            patch("notifications.channels.email.EmailChannel"),
        ):
            flush_email_digests()

        assert cache.get(failure_key) is None


########################################################################
########################################################################
#
class TestPurgeOldNotifications:
    """Tests for purge_old_notifications()."""

    ####################################################################
    #
    def test_deletes_old_notifications(
        self,
        notification_factory: Callable,
        settings,
    ) -> None:
        """
        GIVEN: notifications older and newer than the retention window
        WHEN:  purge_old_notifications() is called
        THEN:  only the old notifications are deleted
        """
        settings.NOTIFICATIONS_RETENTION_DAYS = 30

        with freeze_time("2026-04-01"):
            old = notification_factory()  # 50 days before the purge run

        with freeze_time("2026-05-10"):
            recent = notification_factory()  # 11 days before the purge run

        with freeze_time("2026-05-21"):
            purge_old_notifications()

        assert not Notification.objects.filter(pk=old.pk).exists()
        assert Notification.objects.filter(pk=recent.pk).exists()

    ####################################################################
    #
    def test_deletes_orphaned_log_entries(
        self,
        notification_log_factory: Callable,
        settings,
    ) -> None:
        """
        GIVEN: an old NotificationLog with no notifications referencing it
        WHEN:  purge_old_notifications() is called
        THEN:  the orphaned log entry is deleted
        """
        settings.NOTIFICATIONS_RETENTION_DAYS = 30

        with freeze_time("2026-04-01"):
            log = notification_log_factory()

        with freeze_time("2026-05-21"):
            purge_old_notifications()

        assert not NotificationLog.objects.filter(pk=log.pk).exists()

    ####################################################################
    #
    def test_keeps_log_with_recent_notification(
        self,
        notification_factory: Callable,
        notification_log_factory: Callable,
        settings,
    ) -> None:
        """
        GIVEN: an old NotificationLog that a recent Notification still references
        WHEN:  purge_old_notifications() is called
        THEN:  the log entry is preserved because the recent notification references it
        """
        settings.NOTIFICATIONS_RETENTION_DAYS = 30

        with freeze_time("2026-04-01"):
            log = notification_log_factory()

        with freeze_time("2026-05-10"):
            notification_factory(log_entry=log)  # recent, points at old log

        with freeze_time("2026-05-21"):
            purge_old_notifications()

        assert NotificationLog.objects.filter(pk=log.pk).exists()
