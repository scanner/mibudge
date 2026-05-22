#!/usr/bin/env python
#
"""Tests for notifications.service."""

from collections.abc import Callable
from unittest.mock import MagicMock, patch

import pytest
from notifications.models import (
    Channel,
    Notification,
    NotificationPreference,
    NotificationPriority,
)
from notifications.registry import NotificationRegistry
from notifications.service import notify, notify_account_owners

from users.models import User

pytestmark = pytest.mark.django_db


########################################################################
########################################################################
#
class TestNotify:
    """Tests for notify()."""

    ####################################################################
    #
    @pytest.fixture(autouse=True)
    def isolated_registry(self):
        """
        Replace the global registry with a fresh one for each test so
        registrations in one test don't bleed into others.
        """
        fresh = NotificationRegistry()
        with patch("notifications.service.registry", fresh):
            fresh.register(
                kind="test.normal",
                display_name="Normal test",
                default_priority=NotificationPriority.NORMAL,
                can_suppress=True,
                default_opt_in=True,
            )
            fresh.register(
                kind="test.critical",
                display_name="Critical test",
                default_priority=NotificationPriority.CRITICAL,
                can_suppress=False,
                default_opt_in=True,
            )
            fresh.register(
                kind="test.low_opt_out",
                display_name="Low default-off test",
                default_priority=NotificationPriority.LOW,
                can_suppress=True,
                default_opt_in=False,
            )
            yield fresh

    ####################################################################
    #
    def test_creates_notification_row(self, user: User):
        """
        GIVEN: a registered normal kind
        WHEN:  notify() is called
        THEN:  a Notification row is created with the correct fields
        """
        result = notify(user, "test.normal", {"key": "val"})

        assert result is not None
        assert result.user == user
        assert result.kind == "test.normal"
        assert result.priority == NotificationPriority.NORMAL
        assert result.context == {"key": "val"}
        assert result.channel == Channel.EMAIL
        assert result.log_entry is None

    ####################################################################
    #
    def test_unknown_kind_raises(self, user: User):
        """
        GIVEN: an unregistered kind string
        WHEN:  notify() is called
        THEN:  ValueError is raised
        """
        with pytest.raises(ValueError, match="Unknown notification kind"):
            notify(user, "nonexistent.kind", {})

    ####################################################################
    #
    @pytest.mark.parametrize(
        "kind,explicit_pref,expected_created",
        [
            ("test.normal", None, True),  # default opt-in=True, no pref row
            ("test.normal", False, False),  # explicit opt-out overrides default
            ("test.normal", True, True),  # explicit opt-in matches default
            (
                "test.low_opt_out",
                None,
                False,
            ),  # default opt-in=False, no pref row
            (
                "test.low_opt_out",
                True,
                True,
            ),  # explicit opt-in overrides default
        ],
    )
    def test_preference_gate(
        self,
        user: User,
        kind: str,
        explicit_pref: bool | None,
        expected_created: bool,
    ):
        """
        GIVEN: various opt-in defaults and explicit NotificationPreference rows
        WHEN:  notify() is called for a suppressible kind
        THEN:  a Notification is created iff the user is effectively opted in
        """
        if explicit_pref is not None:
            NotificationPreference.objects.create(
                user=user, kind=kind, enabled=explicit_pref
            )

        result = notify(user, kind, {})

        if expected_created:
            assert result is not None
            assert Notification.objects.filter(user=user, kind=kind).exists()
        else:
            assert result is None
            assert not Notification.objects.filter(
                user=user, kind=kind
            ).exists()

    ####################################################################
    #
    def test_critical_bypasses_preferences(self, user: User):
        """
        GIVEN: a kind with can_suppress=False and an explicit opt-out row
        WHEN:  notify() is called
        THEN:  a Notification is created regardless of the preference
        """
        NotificationPreference.objects.create(
            user=user, kind="test.critical", enabled=False
        )

        with patch("notifications.tasks.send_notification_now"):
            result = notify(user, "test.critical", {})

        assert result is not None

    ####################################################################
    #
    @pytest.mark.parametrize(
        "kind,priority_override,expect_immediate,expected_priority",
        [
            # CRITICAL kind → immediate dispatch, CRITICAL priority stored
            ("test.critical", None, True, NotificationPriority.CRITICAL),
            # NORMAL kind → digest path, NORMAL priority stored
            ("test.normal", None, False, NotificationPriority.NORMAL),
            # Caller overrides priority to CRITICAL → immediate dispatch
            (
                "test.normal",
                NotificationPriority.CRITICAL,
                True,
                NotificationPriority.CRITICAL,
            ),
            # Caller overrides to HIGH → digest path (only CRITICAL is immediate)
            (
                "test.normal",
                NotificationPriority.HIGH,
                False,
                NotificationPriority.HIGH,
            ),
        ],
    )
    def test_dispatch_and_priority(
        self,
        user: User,
        kind: str,
        priority_override: int | None,
        expect_immediate: bool,
        expected_priority: int,
    ):
        """
        GIVEN: various kind/priority combinations
        WHEN:  notify() is called
        THEN:  the stored priority is correct and the immediate Celery task
               is enqueued only for CRITICAL priority
        """
        with patch("notifications.tasks.send_notification_now") as mock_task:
            result = notify(user, kind, {}, priority=priority_override)

        assert result is not None
        assert result.priority == expected_priority

        if expect_immediate:
            mock_task.delay.assert_called_once_with(str(result.id))
        else:
            mock_task.delay.assert_not_called()


########################################################################
########################################################################
#
class TestNotifyAccountOwners:
    """Tests for notify_account_owners()."""

    ####################################################################
    #
    @pytest.fixture(autouse=True)
    def isolated_registry(self):
        fresh = NotificationRegistry()
        with patch("notifications.service.registry", fresh):
            fresh.register(
                kind="test.event",
                display_name="Test event",
                default_priority=NotificationPriority.NORMAL,
                can_suppress=True,
                default_opt_in=True,
            )
            yield fresh

    ####################################################################
    #
    def test_notifies_all_owners(
        self,
        user_factory: Callable,
    ):
        """
        GIVEN: an account with two owners
        WHEN:  notify_account_owners() is called
        THEN:  one Notification is created per owner
        """
        owner_a = user_factory()
        owner_b = user_factory()
        account = MagicMock()
        account.owners.all.return_value = [owner_a, owner_b]

        results = notify_account_owners(account, "test.event", {"x": 1})

        assert len(results) == 2
        assert {n.user_id for n in results} == {owner_a.pk, owner_b.pk}

    ####################################################################
    #
    def test_respects_individual_opt_outs(
        self,
        user_factory: Callable,
    ):
        """
        GIVEN: an account with two owners where one has opted out
        WHEN:  notify_account_owners() is called
        THEN:  only the opted-in owner receives a Notification
        """
        opted_in = user_factory()
        opted_out = user_factory()
        account = MagicMock()
        account.owners.all.return_value = [opted_in, opted_out]
        NotificationPreference.objects.create(
            user=opted_out, kind="test.event", enabled=False
        )

        results = notify_account_owners(account, "test.event", {})

        assert len(results) == 1
        assert results[0].user == opted_in
