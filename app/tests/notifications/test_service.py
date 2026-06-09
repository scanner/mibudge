#!/usr/bin/env python
#
"""Tests for notifications.service."""

from collections.abc import Callable
from unittest.mock import MagicMock, patch  # patch used for registry isolation

import pytest

from notifications.models import (
    Channel,
    DeliveryMode,
    Notification,
    NotificationPreference,
    NotificationPriority,
)
from notifications.registry import NotificationRegistry
from notifications.service import notify, notify_for
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
                default_delivery_mode=DeliveryMode.DIGEST,
            )
            fresh.register(
                kind="test.critical",
                display_name="Critical test",
                default_priority=NotificationPriority.CRITICAL,
                can_suppress=False,
                default_delivery_mode=DeliveryMode.IMMEDIATE,
            )
            fresh.register(
                kind="test.default_off",
                display_name="Default-off test",
                default_priority=NotificationPriority.LOW,
                can_suppress=True,
                default_delivery_mode=DeliveryMode.OFF,
            )
            fresh.register(
                kind="test.default_immediate",
                display_name="Default-immediate test",
                default_priority=NotificationPriority.NORMAL,
                can_suppress=True,
                default_delivery_mode=DeliveryMode.IMMEDIATE,
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
        "kind,stored_mode,expected_created",
        [
            # No DB row -- falls through to registry default_delivery_mode.
            ("test.normal", None, True),  # default digest -> created
            ("test.default_off", None, False),  # default off -> suppressed
            (
                "test.default_immediate",
                None,
                True,
            ),  # default immediate -> created
            # Stored preference overrides the registry default.
            ("test.normal", DeliveryMode.OFF, False),  # opt out
            ("test.normal", DeliveryMode.IMMEDIATE, True),  # explicit immediate
            ("test.default_off", DeliveryMode.DIGEST, True),  # opt back in
        ],
    )
    def test_delivery_mode_gate(
        self,
        user: User,
        kind: str,
        stored_mode: str | None,
        expected_created: bool,
        mock_send_notification_now: MagicMock,
    ):
        """
        GIVEN: various default delivery modes and explicit NotificationPreference rows
        WHEN:  notify() is called for a suppressible kind
        THEN:  a Notification is created iff the effective delivery mode is not 'off'
        """
        if stored_mode is not None:
            NotificationPreference.objects.create(
                user=user, kind=kind, delivery_mode=stored_mode
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
    def test_non_suppressible_always_sent(
        self,
        user: User,
        mock_send_notification_now: MagicMock,
    ):
        """
        GIVEN: a kind with can_suppress=False
        WHEN:  notify() is called (with no preference row -- none can exist)
        THEN:  a Notification is always created and sent immediately
        """
        result = notify(user, "test.critical", {})

        assert result is not None
        mock_send_notification_now.delay.assert_called_once_with(str(result.id))

    ####################################################################
    #
    @pytest.mark.parametrize(
        "kind,stored_mode,priority_override,expect_immediate,expected_priority",
        [
            # Non-suppressible kind -> always immediate, CRITICAL priority stored.
            ("test.critical", None, None, True, NotificationPriority.CRITICAL),
            # NORMAL kind, digest mode -> digest path, NORMAL priority stored.
            ("test.normal", None, None, False, NotificationPriority.NORMAL),
            # NORMAL kind, user set immediate -> immediate dispatch.
            (
                "test.normal",
                DeliveryMode.IMMEDIATE,
                None,
                True,
                NotificationPriority.NORMAL,
            ),
            # Caller overrides priority to CRITICAL -> immediate dispatch
            # regardless of delivery mode.
            (
                "test.normal",
                None,
                NotificationPriority.CRITICAL,
                True,
                NotificationPriority.CRITICAL,
            ),
            # Caller overrides to HIGH -> digest path (only CRITICAL forces
            # immediate via priority override).
            (
                "test.normal",
                None,
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
        stored_mode: str | None,
        priority_override: int | None,
        expect_immediate: bool,
        expected_priority: int,
        mock_send_notification_now: MagicMock,
    ):
        """
        GIVEN: various kind/delivery mode/priority combinations
        WHEN:  notify() is called
        THEN:  the stored priority is correct and immediate dispatch fires
               only when the delivery mode is 'immediate' or priority is CRITICAL
        """
        if stored_mode is not None:
            NotificationPreference.objects.create(
                user=user, kind=kind, delivery_mode=stored_mode
            )

        result = notify(user, kind, {}, priority=priority_override)

        assert result is not None
        assert result.priority == expected_priority

        if expect_immediate:
            mock_send_notification_now.delay.assert_called_once_with(
                str(result.id)
            )
        else:
            mock_send_notification_now.delay.assert_not_called()


########################################################################
########################################################################
#
class TestNotifyFor:
    """Tests for notify_for()."""

    ####################################################################
    #
    @pytest.fixture(autouse=True)
    def isolated_registry(self, user_factory: Callable):
        fresh = NotificationRegistry()
        with patch("notifications.service.registry", fresh):
            self._owner_a = user_factory()
            self._owner_b = user_factory()
            fresh.register(
                kind="test.event",
                display_name="Test event",
                default_priority=NotificationPriority.NORMAL,
                can_suppress=True,
                default_delivery_mode=DeliveryMode.DIGEST,
                recipients=lambda obj: obj.owners.all(),
            )
            fresh.register(
                kind="test.no_recipients",
                display_name="No recipients kind",
                default_priority=NotificationPriority.NORMAL,
                can_suppress=True,
                default_delivery_mode=DeliveryMode.DIGEST,
            )
            yield fresh

    ####################################################################
    #
    def test_notifies_all_recipients(self):
        """
        GIVEN: a kind with a recipients callable returning two users
        WHEN:  notify_for() is called
        THEN:  one Notification is created per recipient
        """
        account = MagicMock()
        account.owners.all.return_value = [self._owner_a, self._owner_b]

        results = notify_for(account, "test.event", {"x": 1})

        assert len(results) == 2
        assert {n.user_id for n in results} == {
            self._owner_a.pk,
            self._owner_b.pk,
        }

    ####################################################################
    #
    def test_respects_individual_opt_outs(self):
        """
        GIVEN: a recipients callable returning two users, one set to 'off'
        WHEN:  notify_for() is called
        THEN:  only the non-suppressed recipient receives a Notification
        """
        account = MagicMock()
        account.owners.all.return_value = [self._owner_a, self._owner_b]
        NotificationPreference.objects.create(
            user=self._owner_b,
            kind="test.event",
            delivery_mode=DeliveryMode.OFF,
        )

        results = notify_for(account, "test.event", {})

        assert len(results) == 1
        assert results[0].user == self._owner_a

    ####################################################################
    #
    def test_missing_recipients_raises(self):
        """
        GIVEN: a kind registered without a recipients callable
        WHEN:  notify_for() is called
        THEN:  ValueError is raised with a helpful message
        """
        with pytest.raises(ValueError, match="no recipients callable"):
            notify_for(MagicMock(), "test.no_recipients", {})
