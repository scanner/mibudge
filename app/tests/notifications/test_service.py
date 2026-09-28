#!/usr/bin/env python
#
"""Tests for notifications.service."""

# system imports
from collections.abc import Callable
from unittest.mock import MagicMock, call

# 3rd party imports
import pytest
import pytest_check as check
from pytest_mock import MockerFixture

# Project imports
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


####################################################################
#
@pytest.fixture
def fresh_registry(mocker: MockerFixture) -> NotificationRegistry:
    """Swap the service's global registry for an empty one.

    Registrations a test makes stay out of every other test.
    """
    fresh = NotificationRegistry()
    mocker.patch("notifications.service.registry", fresh)
    return fresh


########################################################################
########################################################################
#
class TestNotify:
    """Tests for notify()."""

    ####################################################################
    #
    @pytest.fixture(autouse=True)
    def kinds(self, fresh_registry: NotificationRegistry) -> None:
        """Register one kind per delivery-mode / priority combination."""
        fresh_registry.register(
            kind="test.normal",
            display_name="Normal test",
            default_priority=NotificationPriority.NORMAL,
            can_suppress=True,
            default_delivery_mode=DeliveryMode.DIGEST,
        )
        fresh_registry.register(
            kind="test.critical",
            display_name="Critical test",
            default_priority=NotificationPriority.CRITICAL,
            can_suppress=False,
            default_delivery_mode=DeliveryMode.IMMEDIATE,
        )
        fresh_registry.register(
            kind="test.default_off",
            display_name="Default-off test",
            default_priority=NotificationPriority.LOW,
            can_suppress=True,
            default_delivery_mode=DeliveryMode.OFF,
        )
        fresh_registry.register(
            kind="test.default_immediate",
            display_name="Default-immediate test",
            default_priority=NotificationPriority.NORMAL,
            can_suppress=True,
            default_delivery_mode=DeliveryMode.IMMEDIATE,
        )

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
        check.equal(result.user, user, "for the user")
        check.equal(result.kind, "test.normal", "of the kind")
        check.equal(
            result.priority, NotificationPriority.NORMAL, "kind's priority"
        )
        check.equal(result.context, {"key": "val"}, "with the context")
        check.equal(result.channel, Channel.EMAIL, "on the email channel")
        check.is_none(result.log_entry, "not yet sent")

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
        notification_preference_factory: Callable[..., NotificationPreference],
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
            notification_preference_factory(
                user=user, kind=kind, delivery_mode=stored_mode
            )

        result = notify(user, kind, {})

        check.equal(result is not None, expected_created, "returned")
        check.equal(
            Notification.objects.filter(user=user, kind=kind).exists(),
            expected_created,
            "stored",
        )

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
        notification_preference_factory: Callable[..., NotificationPreference],
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
            notification_preference_factory(
                user=user, kind=kind, delivery_mode=stored_mode
            )

        result = notify(user, kind, {}, priority=priority_override)

        assert result is not None
        check.equal(result.priority, expected_priority, "priority stored")
        check.equal(
            mock_send_notification_now.delay.call_args_list,
            [call(str(result.id))] if expect_immediate else [],
            "sent immediately or left for the digest",
        )


########################################################################
########################################################################
#
class TestNotifyFor:
    """Tests for notify_for()."""

    ####################################################################
    #
    @pytest.fixture(autouse=True)
    def kinds(self, fresh_registry: NotificationRegistry) -> None:
        """Register a kind with a recipients callable and one without."""
        fresh_registry.register(
            kind="test.event",
            display_name="Test event",
            default_priority=NotificationPriority.NORMAL,
            can_suppress=True,
            default_delivery_mode=DeliveryMode.DIGEST,
            recipients=lambda obj: obj.owners.all(),
        )
        fresh_registry.register(
            kind="test.no_recipients",
            display_name="No recipients kind",
            default_priority=NotificationPriority.NORMAL,
            can_suppress=True,
            default_delivery_mode=DeliveryMode.DIGEST,
        )

    ####################################################################
    #
    @pytest.fixture
    def owners(self, user_factory: Callable[..., User]) -> list[User]:
        """Two users who both own the account notified about."""
        return [user_factory(), user_factory()]

    ####################################################################
    #
    @pytest.fixture
    def account(self, owners: list[User]) -> MagicMock:
        """A stand-in account whose `owners` are the `owners` fixture."""
        account = MagicMock()
        account.owners.all.return_value = owners
        return account

    ####################################################################
    #
    def test_notifies_all_recipients(
        self, account: MagicMock, owners: list[User]
    ) -> None:
        """
        GIVEN: a kind with a recipients callable returning two users
        WHEN:  notify_for() is called
        THEN:  one Notification is created per recipient
        """
        results = notify_for(account, "test.event", {"x": 1})

        assert sorted(n.user_id for n in results) == sorted(
            o.pk for o in owners
        )

    ####################################################################
    #
    def test_respects_individual_opt_outs(
        self,
        account: MagicMock,
        owners: list[User],
        notification_preference_factory: Callable[..., NotificationPreference],
    ) -> None:
        """
        GIVEN: a recipients callable returning two users, one set to 'off'
        WHEN:  notify_for() is called
        THEN:  only the non-suppressed recipient receives a Notification
        """
        opted_in, opted_out = owners
        notification_preference_factory(
            user=opted_out, kind="test.event", delivery_mode=DeliveryMode.OFF
        )

        results = notify_for(account, "test.event", {})

        assert [n.user for n in results] == [opted_in]

    ####################################################################
    #
    def test_missing_recipients_raises(self) -> None:
        """
        GIVEN: a kind registered without a recipients callable
        WHEN:  notify_for() is called
        THEN:  ValueError is raised with a helpful message
        """
        with pytest.raises(ValueError, match="no recipients callable"):
            notify_for(MagicMock(), "test.no_recipients", {})
