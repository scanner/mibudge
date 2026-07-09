"""Tests for users Celery tasks."""

# system imports
#

from datetime import timedelta

# 3rd party imports
#
import pytest
from celery.result import EagerResult
from django.conf import LazySettings
from django.utils import timezone
from freezegun import freeze_time

# app imports
#
from notifications.models import Notification
from tests.users.factories import UserFactory
from users.models import APIKey, User
from users.notification_kinds import API_KEY_EXPIRING
from users.tasks import get_users_count, notify_expiring_api_keys

pytestmark = pytest.mark.django_db


########################################################################
########################################################################
#
class TestGetUsersCountTask:
    """Tests for the get_users_count Celery task."""

    def test_returns_correct_count(self, settings: LazySettings) -> None:
        """
        GIVEN: three users created via the factory
        WHEN:  the get_users_count task is executed eagerly
        THEN:  the task returns an EagerResult whose value matches the
               database count of User objects
        """
        UserFactory.create_batch(3)
        num_user_objects = User.objects.count()
        settings.CELERY_TASK_ALWAYS_EAGER = True

        task_result = get_users_count.delay()

        assert isinstance(task_result, EagerResult)
        assert task_result.result == num_user_objects


########################################################################
########################################################################
#
class TestNotifyExpiringApiKeys:
    """Tests for the notify_expiring_api_keys periodic task."""

    ################################################################
    #
    @pytest.mark.parametrize(
        "scenario,expires_in_days,revoked,already_notified,expect_notice",
        [
            ("inside the notice window", 7, False, False, True),
            ("last day of the window", 13, False, False, True),
            ("outside the window", 30, False, False, False),
            ("never expires", None, False, False, False),
            ("already expired", -1, False, False, False),
            ("revoked", 7, True, False, False),
            ("already notified", 7, False, True, False),
        ],
    )
    # Frozen so the task computes days_left from the same 'now' the
    # expiry was derived from; otherwise the sub-second lag makes
    # (expires_at - now).days come out one day short.
    @freeze_time("2026-07-09 12:00:00")
    def test_notifies_only_active_keys_inside_window(
        self,
        user: User,
        scenario: str,
        expires_in_days: int | None,
        revoked: bool,
        already_notified: bool,
        expect_notice: bool,
    ) -> None:
        """
        GIVEN: an API key in a particular expiry/revocation/notified state
        WHEN:  notify_expiring_api_keys() runs
        THEN:  only active, not-yet-notified keys expiring inside the
               notice window produce a notification, and the send is
               recorded in expiry_notified_at
        """
        now = timezone.now()
        expires_at = (
            None
            if expires_in_days is None
            else now + timedelta(days=expires_in_days)
        )
        api_key, _ = APIKey.make(user, "importer", expires_at=expires_at)
        if revoked:
            api_key.revoke()
        if already_notified:
            api_key.expiry_notified_at = now - timedelta(days=1)
            api_key.save(update_fields=["expiry_notified_at"])

        notify_expiring_api_keys()

        notices = Notification.objects.filter(kind=API_KEY_EXPIRING)
        assert notices.exists() == expect_notice, scenario
        if expect_notice:
            api_key.refresh_from_db()
            assert api_key.expiry_notified_at is not None
            notice = notices.get()
            assert notice.user == user
            assert notice.context["key_name"] == "importer"
            assert notice.context["key_prefix"] == api_key.prefix
            assert notice.context["days_left"] == expires_in_days
            assert notice.context["expires_at"]

    ################################################################
    #
    def test_each_key_is_warned_exactly_once(self, user: User) -> None:
        """
        GIVEN: a key inside the notice window that was already processed
               by one task run
        WHEN:  notify_expiring_api_keys() runs again
        THEN:  no second notification is created for that key
        """
        APIKey.make(
            user, "importer", expires_at=timezone.now() + timedelta(days=7)
        )

        notify_expiring_api_keys()
        notify_expiring_api_keys()

        assert Notification.objects.filter(kind=API_KEY_EXPIRING).count() == 1

    ################################################################
    #
    def test_notice_window_is_configurable(
        self, user: User, settings: LazySettings
    ) -> None:
        """
        GIVEN: API_KEY_EXPIRY_NOTICE_DAYS lowered to 3
        WHEN:  notify_expiring_api_keys() runs against a key expiring in 7 days
        THEN:  no notification is sent (7 days is outside the 3-day window)
        """
        settings.API_KEY_EXPIRY_NOTICE_DAYS = 3
        APIKey.make(
            user, "importer", expires_at=timezone.now() + timedelta(days=7)
        )

        notify_expiring_api_keys()

        assert not Notification.objects.filter(kind=API_KEY_EXPIRING).exists()
