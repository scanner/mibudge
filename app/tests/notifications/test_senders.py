#!/usr/bin/env python
#
"""Tests for notifications.senders."""

import pytest
from notifications.senders import get_sender


########################################################################
########################################################################
#
class TestGetSender:
    """Tests for get_sender()."""

    ####################################################################
    #
    @pytest.fixture(autouse=True)
    def sender_settings(self, settings) -> None:
        settings.NOTIFICATION_SENDERS = [
            (
                "notifications",
                "App Notifications",
                "notifications@example.com",
                "",
                "",
            ),
            (
                "admin",
                "App Admin",
                "admin@example.com",
                "admin@example.com",
                "s3cr3t",
            ),
        ]
        settings.NOTIFICATION_DEFAULT_SENDER = "notifications"

    ####################################################################
    #
    @pytest.mark.parametrize(
        "sender_id,expected_id,expected_from_email,expected_smtp_user",
        [
            pytest.param(
                None,
                "notifications",
                "notifications@example.com",
                "",
                id="none-resolves-to-default",
            ),
            pytest.param(
                "",
                "notifications",
                "notifications@example.com",
                "",
                id="empty-string-resolves-to-default",
            ),
            pytest.param(
                "notifications",
                "notifications",
                "notifications@example.com",
                "",
                id="api-sender-no-smtp-credentials",
            ),
            pytest.param(
                "admin",
                "admin",
                "admin@example.com",
                "admin@example.com",
                id="smtp-sender-with-credentials",
            ),
        ],
    )
    def test_resolves_sender(
        self,
        sender_id: str | None,
        expected_id: str,
        expected_from_email: str,
        expected_smtp_user: str,
    ) -> None:
        """
        GIVEN: NOTIFICATION_SENDERS with an API sender and an SMTP sender
        WHEN:  get_sender() is called with various sender_id values
        THEN:  the correct SenderConfig is returned with the right fields
        """
        config = get_sender(sender_id)

        assert config.id == expected_id
        assert config.from_email == expected_from_email
        assert config.smtp_user == expected_smtp_user

    ####################################################################
    #
    def test_smtp_sender_password(self) -> None:
        """
        GIVEN: a sender with smtp_password configured
        WHEN:  get_sender() is called for that sender
        THEN:  the password is present on the returned config
        """
        config = get_sender("admin")
        assert config.smtp_password == "s3cr3t"

    ####################################################################
    #
    @pytest.mark.parametrize(
        "bad_id",
        [
            pytest.param("nonexistent", id="unknown-explicit-id"),
        ],
    )
    def test_raises_for_unknown_id(self, bad_id: str) -> None:
        """
        GIVEN: a sender ID that does not exist in NOTIFICATION_SENDERS
        WHEN:  get_sender() is called with that ID
        THEN:  ValueError is raised with a descriptive message
        """
        with pytest.raises(ValueError, match="Unknown notification sender"):
            get_sender(bad_id)

    ####################################################################
    #
    def test_raises_when_default_is_unknown(self, settings) -> None:
        """
        GIVEN: NOTIFICATION_DEFAULT_SENDER names a non-existent sender
        WHEN:  get_sender(None) is called
        THEN:  ValueError is raised
        """
        settings.NOTIFICATION_DEFAULT_SENDER = "doesnotexist"

        with pytest.raises(ValueError, match="Unknown notification sender"):
            get_sender(None)

    ####################################################################
    #
    def test_sender_config_is_frozen(self) -> None:
        """
        GIVEN: a SenderConfig returned by get_sender()
        WHEN:  an attribute assignment is attempted
        THEN:  the dataclass raises because it is frozen
        """
        config = get_sender("notifications")

        with pytest.raises((AttributeError, TypeError)):
            config.id = "tampered"  # type: ignore[misc]
