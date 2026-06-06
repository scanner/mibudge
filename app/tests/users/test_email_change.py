#!/usr/bin/env python
#
"""
Tests for the self-service email-address change feature.

Two primary flows are covered, each with sub-cases and edge cases:

Flow A -- email change accepted
  1. Initiate: POST change-email → request created, emails sent
  2. Confirm:  POST confirm/     → address updated, revocation window open
  3. Lockout:  POST change-email within window → 409
  4. Unlock:   POST change-email after window closes → 201

Flow B -- 'this wasn't me' revocation
  B1. Pre-confirmation: revoke before new address confirms
      → email unchanged, sessions unaffected
  B2. Post-confirmation: revoke after new address confirms
      → email reverted, all sessions killed

Session invalidation is verified by checking whether outstanding
refresh tokens still produce a 200 from the token-refresh endpoint
after the operation.
"""

# system imports
#
from collections.abc import Callable
from datetime import timedelta

# 3rd party imports
#
import pytest
from django.core import mail
from django.test import Client
from django.urls import reverse
from freezegun import freeze_time

# Project imports
#
from notifications.models import Notification
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from users.models import EmailChangeRequest, User
from users.notification_kinds import (
    EMAIL_CHANGE_REQUESTED,
    EMAIL_CHANGE_SECURITY_ALERT,
)
from users.views import REFRESH_COOKIE_NAME

pytestmark = pytest.mark.django_db

########################################################################
# URL helpers -- use reverse() so a URL restructure surfaces here
# as a NoReverseMatch rather than a silent wrong-path assertion.
########################################################################


def _change_email_url() -> str:
    return reverse("api_v1:user-change-email")


def _confirm_url(token: str) -> str:
    return reverse("api_v1:user-change-email-confirm", kwargs={"token": token})


def _revoke_url(token: str) -> str:
    return reverse("api_v1:user-change-email-revoke", kwargs={"token": token})


def _token_obtain_url() -> str:
    return reverse("token-obtain")


def _token_refresh_url() -> str:
    return reverse("token-refresh")


########################################################################
# Shared fixtures
########################################################################


@pytest.fixture(autouse=True)
def email_change_settings(settings) -> None:
    """Override settings required by the email-change service in tests."""
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.SITE_URL = "http://testserver"
    settings.SITE_DISPLAY_NAME = "MiBudge [test]"
    settings.SUPPORT_EMAIL = "support@test.example.com"


@pytest.fixture
def known_password() -> str:
    return "CorrectHorseBatteryStaple1!"


@pytest.fixture
def alice(user_factory: Callable[..., User], known_password: str) -> User:
    """A user with a known email and a usable password."""
    return user_factory(email="alice@example.com", password=known_password)


@pytest.fixture
def auth_client(alice: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=alice)
    return client


def _refresh_client(refresh: RefreshToken) -> Client:
    """Return a Django test Client pre-loaded with the given refresh cookie."""
    c = Client()
    c.cookies[REFRESH_COOKIE_NAME] = str(refresh)
    return c


def _session_valid(refresh: RefreshToken) -> bool:
    """True if the refresh token still produces an access token."""
    return (
        _refresh_client(refresh).post(_token_refresh_url()).status_code
        == status.HTTP_200_OK
    )


def _get_ecr(user: User) -> EmailChangeRequest:
    return EmailChangeRequest.objects.get(user=user)


########################################################################
########################################################################
#
class TestFlowA:
    """Flow A: email change accepted (happy path)."""

    ####################################################################
    #
    def test_step1_creates_request_and_sends_emails(
        self,
        alice: User,
        auth_client: APIClient,
        mock_send_notification_now,
    ) -> None:
        """
        GIVEN: a user with a usable password; refresh token RT-A held
        WHEN:  POST change-email with new_email
        THEN:  201; EmailChangeRequest created with correct fields;
               verification email sent to new address;
               notification queued for old address via notification system;
               User.email unchanged; RT-A still valid
        """
        rt_a = RefreshToken.for_user(alice)

        response = auth_client.post(
            _change_email_url(), {"new_email": "new@example.com"}
        )

        assert response.status_code == status.HTTP_201_CREATED

        ecr = _get_ecr(alice)
        assert ecr.old_email == "alice@example.com"
        assert ecr.new_email == "new@example.com"
        assert ecr.confirmed_at is None
        assert ecr.revoked_at is None
        assert ecr.revocable_until is None
        assert not ecr.is_expired

        alice.refresh_from_db()
        assert alice.email == "alice@example.com"  # unchanged

        # Verification email goes directly to new address
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["new@example.com"]

        # Notification queued for old address via notification system
        assert Notification.objects.filter(
            user=alice, kind=EMAIL_CHANGE_REQUESTED
        ).exists()

        # Existing session unaffected
        assert _session_valid(rt_a)

    ####################################################################
    #
    def test_step2_confirm_updates_email_and_opens_window(
        self,
        alice: User,
        auth_client: APIClient,
        mock_send_notification_now,
    ) -> None:
        """
        GIVEN: a pending EmailChangeRequest; RT-A held
        WHEN:  POST confirm/
        THEN:  200; User.email = new_email; confirmed_at + revocable_until set;
               no additional emails; RT-A still valid (confirmation does not
               invalidate sessions -- only revocation does)
        """
        auth_client.post(_change_email_url(), {"new_email": "new@example.com"})
        ecr = _get_ecr(alice)
        rt_a = RefreshToken.for_user(alice)
        mail.outbox.clear()

        response = auth_client.post(_confirm_url(ecr.token))

        assert response.status_code == status.HTTP_200_OK

        alice.refresh_from_db()
        assert alice.email == "new@example.com"
        assert alice.username == "new@example.com"

        ecr.refresh_from_db()
        assert ecr.confirmed_at is not None
        assert ecr.revocable_until is not None
        assert ecr.revocable_until > ecr.confirmed_at

        assert len(mail.outbox) == 0  # confirmation itself sends no email
        assert _session_valid(rt_a)

    ####################################################################
    #
    def test_step3_new_request_blocked_during_revocation_window(
        self,
        alice: User,
        auth_client: APIClient,
        mock_send_notification_now,
    ) -> None:
        """
        GIVEN: a confirmed EmailChangeRequest within its revocation window
        WHEN:  POST change-email again
        THEN:  409; no second request created; no emails sent
        """
        auth_client.post(_change_email_url(), {"new_email": "new@example.com"})
        ecr = _get_ecr(alice)
        auth_client.post(_confirm_url(ecr.token))
        mail.outbox.clear()

        response = auth_client.post(
            _change_email_url(), {"new_email": "another@example.com"}
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        assert EmailChangeRequest.objects.filter(user=alice).count() == 1
        assert len(mail.outbox) == 0

    ####################################################################
    #
    def test_step4_new_request_allowed_after_window_closes(
        self,
        alice: User,
        auth_client: APIClient,
        mock_send_notification_now,
    ) -> None:
        """
        GIVEN: a confirmed EmailChangeRequest past its revocation window
        WHEN:  POST change-email
        THEN:  201 (lockout lifted)
        """
        auth_client.post(_change_email_url(), {"new_email": "new@example.com"})
        ecr = _get_ecr(alice)
        auth_client.post(_confirm_url(ecr.token))
        ecr.refresh_from_db()

        assert ecr.revocable_until is not None
        past_window = ecr.revocable_until + timedelta(seconds=1)
        with freeze_time(past_window):
            alice.refresh_from_db()
            fresh = APIClient()
            fresh.force_authenticate(user=alice)
            response = fresh.post(
                _change_email_url(), {"new_email": "another@example.com"}
            )

        assert response.status_code == status.HTTP_201_CREATED

    ####################################################################
    # Edge cases
    ####################################################################

    ####################################################################
    #
    def test_no_usable_password_returns_403(
        self, alice: User, auth_client: APIClient
    ) -> None:
        """
        GIVEN: a user with no usable password set
        WHEN:  POST change-email
        THEN:  403
        """
        alice.set_unusable_password()
        alice.save()

        response = auth_client.post(
            _change_email_url(), {"new_email": "new@example.com"}
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    ####################################################################
    #
    def test_new_email_already_taken_returns_409(
        self,
        alice: User,
        auth_client: APIClient,
        user_factory: Callable[..., User],
        mock_send_notification_now,
    ) -> None:
        """
        GIVEN: new_email already belongs to another account
        WHEN:  POST change-email
        THEN:  409; no request created; no email sent
        """
        user_factory(email="taken@example.com")

        response = auth_client.post(
            _change_email_url(), {"new_email": "taken@example.com"}
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        assert not EmailChangeRequest.objects.filter(user=alice).exists()
        assert len(mail.outbox) == 0

    ####################################################################
    #
    def test_expired_token_returns_400(
        self,
        alice: User,
        auth_client: APIClient,
        mock_send_notification_now,
    ) -> None:
        """
        GIVEN: a verification token that has passed its 24-hour expiry
        WHEN:  POST confirm/
        THEN:  400; User.email unchanged
        """
        auth_client.post(_change_email_url(), {"new_email": "new@example.com"})
        ecr = _get_ecr(alice)

        past_expiry = ecr.expires_at + timedelta(seconds=1)
        with freeze_time(past_expiry):
            response = auth_client.post(_confirm_url(ecr.token))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        alice.refresh_from_db()
        assert alice.email == "alice@example.com"

    ####################################################################
    #
    def test_already_confirmed_token_returns_400(
        self,
        alice: User,
        auth_client: APIClient,
        mock_send_notification_now,
    ) -> None:
        """
        GIVEN: a token that has already been confirmed
        WHEN:  POST confirm/ a second time
        THEN:  400
        """
        auth_client.post(_change_email_url(), {"new_email": "new@example.com"})
        ecr = _get_ecr(alice)
        auth_client.post(_confirm_url(ecr.token))

        response = auth_client.post(_confirm_url(ecr.token))

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    ####################################################################
    #
    def test_email_taken_at_confirm_time_returns_409(
        self,
        alice: User,
        auth_client: APIClient,
        user_factory: Callable[..., User],
        mock_send_notification_now,
    ) -> None:
        """
        GIVEN: new_email claimed by another account between request and confirm
        WHEN:  POST confirm/
        THEN:  409; User.email unchanged (race condition is caught at confirm time)
        """
        auth_client.post(
            _change_email_url(), {"new_email": "raced@example.com"}
        )
        ecr = _get_ecr(alice)

        user_factory(
            email="raced@example.com"
        )  # another user registers it first

        response = auth_client.post(_confirm_url(ecr.token))

        assert response.status_code == status.HTTP_409_CONFLICT
        alice.refresh_from_db()
        assert alice.email == "alice@example.com"

    ####################################################################
    #
    def test_revoke_after_window_closed_returns_400(
        self,
        alice: User,
        auth_client: APIClient,
        mock_send_notification_now,
    ) -> None:
        """
        GIVEN: a confirmed EmailChangeRequest past its revocation window
        WHEN:  POST revoke/
        THEN:  400 (the change is now permanent)
        """
        auth_client.post(_change_email_url(), {"new_email": "new@example.com"})
        ecr = _get_ecr(alice)
        auth_client.post(_confirm_url(ecr.token))
        ecr.refresh_from_db()

        assert ecr.revocable_until is not None
        past_window = ecr.revocable_until + timedelta(seconds=1)
        with freeze_time(past_window):
            response = auth_client.post(_revoke_url(ecr.token))

        assert response.status_code == status.HTTP_400_BAD_REQUEST


########################################################################
########################################################################
#
class TestFlowB1:
    """Flow B sub-case 1: revoked before confirmation.

    The request was caught early -- the email was never changed, so
    no session invalidation is needed.
    """

    ####################################################################
    #
    def test_pre_confirmation_revocation(
        self,
        alice: User,
        auth_client: APIClient,
        mock_send_notification_now,
    ) -> None:
        """
        GIVEN: a pending (unconfirmed) EmailChangeRequest; RT-A and RT-B held
        WHEN:  POST revoke/
        THEN:  200; User.email unchanged; RT-A and RT-B still valid;
               security alert sent to both old and new addresses;
               a new change request is immediately allowed
        """
        rt_a = RefreshToken.for_user(alice)
        rt_b = RefreshToken.for_user(alice)

        auth_client.post(
            _change_email_url(), {"new_email": "attacker@evil.com"}
        )
        ecr = _get_ecr(alice)
        assert ecr.confirmed_at is None
        mail.outbox.clear()

        response = auth_client.post(_revoke_url(ecr.token))

        assert response.status_code == status.HTTP_200_OK

        ecr.refresh_from_db()
        assert ecr.revoked_at is not None
        assert ecr.confirmed_at is None

        alice.refresh_from_db()
        assert alice.email == "alice@example.com"  # unchanged

        # No session invalidation -- the email never changed
        assert _session_valid(rt_a)
        assert _session_valid(rt_b)

        # Security alert to attacker's address (direct email)
        assert any("attacker@evil.com" in m.to for m in mail.outbox)

        # Security alert notification queued for alice's address
        assert Notification.objects.filter(
            user=alice, kind=EMAIL_CHANGE_SECURITY_ALERT
        ).exists()

        # No lockout: revocable_until was never set, so a new request is allowed
        mail.outbox.clear()
        response2 = auth_client.post(
            _change_email_url(), {"new_email": "legit@example.com"}
        )
        assert response2.status_code == status.HTTP_201_CREATED


########################################################################
########################################################################
#
class TestFlowB2:
    """Flow B sub-case 2: revoked after confirmation.

    The attacker confirmed before the legitimate user could react.
    Revocation reverts the email and kills all sessions.
    """

    ####################################################################
    #
    def test_post_confirmation_revocation(
        self,
        alice: User,
        auth_client: APIClient,
        mock_send_notification_now,
    ) -> None:
        """
        GIVEN: a confirmed EmailChangeRequest within its revocation window;
               RT-A (alice) and RT-B (attacker) both held
        WHEN:  POST revoke/ at confirmed_at + 3 days
        THEN:  200; User.email reverted; RT-A and RT-B both invalid;
               security alert sent to both addresses;
               second revoke returns 400;
               new request immediately allowed
        """
        rt_a = RefreshToken.for_user(alice)
        rt_b = RefreshToken.for_user(alice)

        auth_client.post(
            _change_email_url(), {"new_email": "attacker@evil.com"}
        )
        ecr = _get_ecr(alice)

        auth_client.post(_confirm_url(ecr.token))
        alice.refresh_from_db()
        assert alice.email == "attacker@evil.com"

        # Both sessions remain valid immediately after confirmation
        assert _session_valid(rt_a)
        assert _session_valid(rt_b)

        ecr.refresh_from_db()
        assert ecr.confirmed_at is not None
        three_days_later = ecr.confirmed_at + timedelta(days=3)
        mail.outbox.clear()

        with freeze_time(three_days_later):
            response = auth_client.post(_revoke_url(ecr.token))

        assert response.status_code == status.HTTP_200_OK

        alice.refresh_from_db()
        assert alice.email == "alice@example.com"  # reverted
        assert alice.username == "alice@example.com"

        ecr.refresh_from_db()
        assert ecr.revoked_at is not None

        # Both sessions now dead
        assert not _session_valid(rt_a)
        assert not _session_valid(rt_b)

        # Security alert to attacker's address
        assert any("attacker@evil.com" in m.to for m in mail.outbox)

        # Security alert notification queued for alice's restored address
        assert Notification.objects.filter(
            user=alice, kind=EMAIL_CHANGE_SECURITY_ALERT
        ).exists()

        # Revoking again is rejected
        assert (
            auth_client.post(_revoke_url(ecr.token)).status_code
            == status.HTTP_400_BAD_REQUEST
        )

        # New request is immediately allowed (revoked_at is set; lockout cleared)
        assert (
            auth_client.post(
                _change_email_url(), {"new_email": "fresh@example.com"}
            ).status_code
            == status.HTTP_201_CREATED
        )

    ####################################################################
    #
    def test_login_with_old_credentials_succeeds_after_revocation(
        self,
        alice: User,
        known_password: str,
        auth_client: APIClient,
        mock_send_notification_now,
    ) -> None:
        """
        GIVEN: a revoked post-confirmation email change
        WHEN:  login attempt with alice's original email and password
        THEN:  200 with access token (account fully usable under restored address)
        """
        auth_client.post(
            _change_email_url(), {"new_email": "attacker@evil.com"}
        )
        ecr = _get_ecr(alice)
        auth_client.post(_confirm_url(ecr.token))
        auth_client.post(_revoke_url(ecr.token))

        unauthenticated = Client()
        response = unauthenticated.post(
            _token_obtain_url(),
            {"email": "alice@example.com", "password": known_password},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert "access" in response.json()
