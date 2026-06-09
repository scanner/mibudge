#!/usr/bin/env python
#
"""
Tests for the admin-initiated user invitation feature.

Covers:
  - Service layer: create, cancel, resend, accept
  - Rate limiting: resend limit boundary, cooldown, rolling window cap
  - Edge cases: already-registered, duplicate pending, expired token,
    double-acceptance, terminal-status rejections
"""

# system imports
#
from collections.abc import Callable
from datetime import timedelta

# 3rd party imports
#
import pytest
from django.core import mail
from django.utils import timezone
from freezegun import freeze_time
from pytest_mock import MockerFixture

# Project imports
#
from users.invitation import (
    InvitationAlreadyPendingError,
    InvitationWindowExceededError,
    InviteeAlreadyRegisteredError,
    ResendCooldownActiveError,
    ResendLimitReachedError,
    TokenAlreadyAcceptedError,
    TokenAlreadyCancelledError,
    TokenExpiredError,
    TokenNotFoundError,
    accept_user_invitation,
    cancel_user_invitation,
    create_user_invitation,
    resend_user_invitation,
)
from users.models import User, UserInvitation

pytestmark = pytest.mark.django_db


########################################################################
# Shared fixtures
########################################################################


@pytest.fixture(autouse=True)
def invitation_settings(settings) -> None:
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.SITE_URL = "http://testserver"
    settings.SITE_DISPLAY_NAME = "MiBudge [test]"
    settings.SUPPORT_EMAIL = "support@test.example.com"
    settings.NOTIFICATIONS_DEFAULT_LOCALE = "en-us"
    settings.INVITATION_EXPIRY_DAYS = 7
    settings.INVITATION_MAX_RESENDS = 3
    settings.INVITATION_RESEND_COOLDOWN_HOURS = 1
    settings.INVITATION_MAX_PER_WINDOW = 5
    settings.INVITATION_WINDOW_DAYS = 30


@pytest.fixture
def admin_user(user_factory: Callable[..., User]) -> User:
    return user_factory(email="admin@example.com")


########################################################################
########################################################################
#
class TestCreateUserInvitation:
    """Service: create_user_invitation() happy paths and rejections."""

    ####################################################################
    #
    def test_new_address_creates_inactive_user_and_sends_email(
        self,
        admin_user: User,
    ) -> None:
        """
        GIVEN: an email not yet in the system
        WHEN:  create_user_invitation() is called
        THEN:  a pending UserInvitation is created; an inactive User is
               created for the invitee; one invitation email is sent
        """
        inv = create_user_invitation(admin_user, "newperson@example.com")

        assert inv.status == UserInvitation.Status.PENDING
        assert inv.invitee_email == "newperson@example.com"
        assert inv.invitee_user is not None
        assert not inv.invitee_user.is_active
        assert not inv.invitee_user.has_usable_password()
        assert inv.send_count == 1
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["newperson@example.com"]

    ####################################################################
    #
    def test_rejects_already_registered_active_user(
        self,
        admin_user: User,
        user_factory: Callable[..., User],
    ) -> None:
        """
        GIVEN: an email that belongs to an existing active account
        WHEN:  create_user_invitation() is called
        THEN:  InviteeAlreadyRegisteredError raised; no invitation created
        """
        user_factory(email="existing@example.com")

        with pytest.raises(InviteeAlreadyRegisteredError):
            create_user_invitation(admin_user, "existing@example.com")

        assert UserInvitation.objects.count() == 0

    ####################################################################
    #
    def test_rejects_duplicate_pending(self, admin_user: User) -> None:
        """
        GIVEN: a pending invitation already exists for an email
        WHEN:  create_user_invitation() targets the same email
        THEN:  InvitationAlreadyPendingError raised
        """
        create_user_invitation(admin_user, "dup@example.com")
        mail.outbox.clear()

        with pytest.raises(InvitationAlreadyPendingError):
            create_user_invitation(admin_user, "dup@example.com")

    ####################################################################
    #
    def test_allows_new_invitation_after_expiry(self, admin_user: User) -> None:
        """
        GIVEN: a previous invitation for an email that has now expired
        WHEN:  create_user_invitation() targets the same email
        THEN:  a new invitation is created without error
        """
        with freeze_time(timezone.now() - timedelta(days=8)):
            create_user_invitation(admin_user, "retry@example.com")
        mail.outbox.clear()

        inv2 = create_user_invitation(admin_user, "retry@example.com")
        assert inv2.status == UserInvitation.Status.PENDING

    ####################################################################
    #
    def test_rejects_when_rolling_window_exceeded(
        self,
        admin_user: User,
        user_invitation_factory: Callable[..., UserInvitation],
    ) -> None:
        """
        GIVEN: 5 invitations (any status) to the same email in the last 30 days
        WHEN:  create_user_invitation() targets the same email
        THEN:  InvitationWindowExceededError raised
        """
        email = "flooded@example.com"
        for _ in range(5):
            user_invitation_factory(
                invitee_email=email,
                status=UserInvitation.Status.CANCELLED,
            )

        with pytest.raises(InvitationWindowExceededError):
            create_user_invitation(admin_user, email)


########################################################################
########################################################################
#
class TestCancelUserInvitation:
    """Service: cancel_user_invitation()."""

    ####################################################################
    #
    def test_cancels_pending_invitation(
        self,
        user_invitation_factory: Callable[..., UserInvitation],
        admin_user: User,
    ) -> None:
        """
        GIVEN: a pending invitation
        WHEN:  cancel_user_invitation() is called
        THEN:  status becomes cancelled; cancelled_at is set
        """
        inv = user_invitation_factory(invited_by=admin_user)
        cancel_user_invitation(inv)

        inv.refresh_from_db()
        assert inv.status == UserInvitation.Status.CANCELLED
        assert inv.cancelled_at is not None

    ####################################################################
    #
    @pytest.mark.parametrize(
        "terminal_status,exc_class",
        [
            (UserInvitation.Status.ACCEPTED, TokenAlreadyAcceptedError),
            (UserInvitation.Status.CANCELLED, TokenAlreadyCancelledError),
            (UserInvitation.Status.EXPIRED, TokenExpiredError),
        ],
    )
    def test_raises_on_terminal_status(
        self,
        terminal_status: str,
        exc_class: type,
        user_invitation_factory: Callable[..., UserInvitation],
    ) -> None:
        """
        GIVEN: an invitation already in a terminal state
        WHEN:  cancel_user_invitation() is called
        THEN:  the appropriate error is raised
        """
        inv = user_invitation_factory(status=terminal_status)
        with pytest.raises(exc_class):
            cancel_user_invitation(inv)


########################################################################
########################################################################
#
class TestResendUserInvitation:
    """Service: resend_user_invitation() -- rate limit enforcement."""

    ####################################################################
    #
    def test_resend_increments_send_count_and_sends_email(
        self,
        user_invitation_factory: Callable[..., UserInvitation],
        admin_user: User,
    ) -> None:
        """
        GIVEN: a pending invitation with send_count=1 and last_sent_at > 1 hour ago
        WHEN:  resend_user_invitation() is called
        THEN:  send_count becomes 2; last_sent_at updated; email sent
        """
        inv = user_invitation_factory(
            invited_by=admin_user,
            last_sent_at=timezone.now() - timedelta(hours=2),
        )

        resend_user_invitation(inv)

        inv.refresh_from_db()
        assert inv.send_count == 2
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [inv.invitee_email]

    ####################################################################
    #
    def test_boundary_third_resend_is_allowed(
        self,
        user_invitation_factory: Callable[..., UserInvitation],
    ) -> None:
        """
        GIVEN: send_count=3 (3 resends already used, exactly at max)
        WHEN:  resend_user_invitation() is called
        THEN:  succeeds -- the block fires at send_count > 3, not >= 3;
               confirming 3 resends total (4 emails) are permitted
        """
        inv = user_invitation_factory(
            send_count=3,
            last_sent_at=timezone.now() - timedelta(hours=2),
        )

        resend_user_invitation(inv)

        inv.refresh_from_db()
        assert inv.send_count == 4
        assert len(mail.outbox) == 1

    ####################################################################
    #
    @pytest.mark.parametrize(
        "send_count,last_sent_minutes_ago,exc_class",
        [
            # send_count=4 exceeds max_resends=3; cooldown has passed
            (4, 120, ResendLimitReachedError),
            # send_count within limit; last sent only 30 min ago (< 1 h cooldown)
            (1, 30, ResendCooldownActiveError),
        ],
    )
    def test_raises_when_resend_is_blocked(
        self,
        send_count: int,
        last_sent_minutes_ago: int,
        exc_class: type,
        user_invitation_factory: Callable[..., UserInvitation],
    ) -> None:
        """
        GIVEN: a pending invitation that violates a rate-limit rule
        WHEN:  resend_user_invitation() is called
        THEN:  the appropriate rate-limit error is raised; no email sent
        """
        inv = user_invitation_factory(
            send_count=send_count,
            last_sent_at=timezone.now()
            - timedelta(minutes=last_sent_minutes_ago),
        )

        with pytest.raises(exc_class):
            resend_user_invitation(inv)

        assert len(mail.outbox) == 0

    ####################################################################
    #
    @pytest.mark.parametrize(
        "terminal_status,exc_class",
        [
            (UserInvitation.Status.ACCEPTED, TokenAlreadyAcceptedError),
            (UserInvitation.Status.CANCELLED, TokenAlreadyCancelledError),
            (UserInvitation.Status.EXPIRED, TokenExpiredError),
        ],
    )
    def test_raises_on_terminal_status(
        self,
        terminal_status: str,
        exc_class: type,
        user_invitation_factory: Callable[..., UserInvitation],
    ) -> None:
        """
        GIVEN: an invitation in a terminal state
        WHEN:  resend_user_invitation() is called
        THEN:  the appropriate error is raised; no email sent

        This also pins the ordering guarantee: _validate_pending() fires
        before check_resend(), so terminal-status short-circuits before
        any rate-limit evaluation (the factory default leaves last_sent_at
        within the cooldown window, so a wrong ordering would produce
        ResendCooldownActiveError instead).
        """
        inv = user_invitation_factory(status=terminal_status)
        with pytest.raises(exc_class):
            resend_user_invitation(inv)
        assert len(mail.outbox) == 0


########################################################################
########################################################################
#
class TestAcceptUserInvitation:
    """Service: accept_user_invitation()."""

    ####################################################################
    #
    def test_activates_user_and_triggers_password_reset(
        self,
        user_invitation_factory: Callable[..., UserInvitation],
        user_factory: Callable[..., User],
        admin_user: User,
        mocker: MockerFixture,
    ) -> None:
        """
        GIVEN: a pending invitation for an inactive, no-password user
        WHEN:  accept_user_invitation() is called
        THEN:  user activated; status = accepted; accepted_at set;
               password-reset email dispatched
        """
        invitee = user_factory(email="newbie@example.com")
        invitee.is_active = False
        invitee.set_unusable_password()
        invitee.save()

        inv = user_invitation_factory(
            invited_by=admin_user,
            invitee_email=invitee.email,
            invitee_user=invitee,
        )

        mock_reset = mocker.patch("users.invitation.trigger_password_reset")
        accept_user_invitation(inv.token)

        mock_reset.assert_called_once_with(invitee, request=None)
        inv.refresh_from_db()
        assert inv.status == UserInvitation.Status.ACCEPTED
        assert inv.accepted_at is not None
        invitee.refresh_from_db()
        assert invitee.is_active

    ####################################################################
    #
    def test_raises_on_wall_clock_expiry_and_marks_status(
        self,
        user_invitation_factory: Callable[..., UserInvitation],
    ) -> None:
        """
        GIVEN: a PENDING invitation whose expires_at is in the past
        WHEN:  accept_user_invitation() is called
        THEN:  TokenExpiredError raised; row status updated to EXPIRED

        Distinct from the stored-EXPIRED parametrize case below: this
        exercises the wall-clock branch in _validate_pending (status is
        still PENDING in the DB but the clock has passed expires_at),
        which also persists the EXPIRED status transition.
        """
        inv = user_invitation_factory(
            expires_at=timezone.now() - timedelta(hours=1),
        )
        with pytest.raises(TokenExpiredError):
            accept_user_invitation(inv.token)

        inv.refresh_from_db()
        assert inv.status == UserInvitation.Status.EXPIRED

    ####################################################################
    #
    def test_raises_on_unknown_token(self) -> None:
        """
        GIVEN: no invitation exists for a token
        WHEN:  accept_user_invitation() is called
        THEN:  TokenNotFoundError raised
        """
        with pytest.raises(TokenNotFoundError):
            accept_user_invitation("does-not-exist")

    ####################################################################
    #
    @pytest.mark.parametrize(
        "terminal_status,exc_class",
        [
            (UserInvitation.Status.ACCEPTED, TokenAlreadyAcceptedError),
            (UserInvitation.Status.CANCELLED, TokenAlreadyCancelledError),
            (UserInvitation.Status.EXPIRED, TokenExpiredError),
        ],
    )
    def test_raises_on_terminal_status(
        self,
        terminal_status: str,
        exc_class: type,
        user_invitation_factory: Callable[..., UserInvitation],
    ) -> None:
        """
        GIVEN: an invitation already in a terminal state
        WHEN:  accept_user_invitation() is called
        THEN:  the appropriate error is raised
        """
        inv = user_invitation_factory(status=terminal_status)
        with pytest.raises(exc_class):
            accept_user_invitation(inv.token)
