#!/usr/bin/env python
#
"""
Tests for the self-service email-address change feature.

Two primary flows are covered, each with sub-cases and edge cases:

Flow A -- email change accepted
  1. Initiate: POST change-email -> request created, emails sent
  2. Confirm:  POST confirm/     -> address updated, revocation window open
  3. Lockout:  POST change-email within window -> 409
  4. Unlock:   POST change-email after window closes -> 201

Flow B -- 'this wasn't me' revocation
  B1. Pre-confirmation: revoke before new address confirms
      -> email unchanged, all sessions killed, API keys listed for review
  B2. Post-confirmation: revoke after new address confirms
      -> email reverted, all sessions killed, API keys revoked

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
import pytest_check as check
from django.core.mail import EmailMessage
from django.test import Client
from django.urls import reverse
from faker import Faker
from freezegun import freeze_time
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

# Project imports
#
from notifications.channels.email import EmailChannel
from notifications.models import Notification
from tests.users.session_checks import session_valid
from users.models import APIKey, EmailChangeRequest, User
from users.notification_kinds import (
    EMAIL_CHANGE_REQUESTED,
    EMAIL_CHANGE_SECURITY_ALERT,
)

# Every flow here queues notifications, which need the Celery send
# patched out.
#
pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures(
        "site_email_settings", "mock_send_notification_now"
    ),
]

# reverse() so a URL restructure surfaces here as a NoReverseMatch rather
# than a silent wrong-path assertion.
#
CHANGE_EMAIL_URL = reverse("api_v1:user-change-email")
TOKEN_OBTAIN_URL = reverse("token-obtain")


####################################################################
#
def _confirm_url(token: str) -> str:
    return reverse("api_v1:user-change-email-confirm", kwargs={"token": token})


####################################################################
#
def _revoke_url(token: str) -> str:
    return reverse("api_v1:user-change-email-revoke", kwargs={"token": token})


####################################################################
#
def _sent_to(outbox: list[EmailMessage], address: str) -> bool:
    """True if any message in `outbox` was addressed to `address`."""
    return any(address in m.to for m in outbox)


####################################################################
#
@pytest.fixture
def known_password() -> str:
    return "CorrectHorseBatteryStaple1!"


####################################################################
#
@pytest.fixture
def old_email(faker: Faker) -> str:
    """Alice's address before any change."""
    return faker.unique.email()


####################################################################
#
@pytest.fixture
def new_email(faker: Faker) -> str:
    """The address a change request asks for."""
    return faker.unique.email()


####################################################################
#
@pytest.fixture
def alice(
    user_factory: Callable[..., User], known_password: str, old_email: str
) -> User:
    """A user with a known email and a usable password."""
    return user_factory(email=old_email, password=known_password)


####################################################################
#
@pytest.fixture
def user(alice: User) -> User:
    """Make alice the default user, so `auth_client` acts as her."""
    return alice


####################################################################
#
@pytest.fixture
def pending_ecr(
    alice: User,
    auth_client: APIClient,
    new_email: str,
    mailoutbox: list[EmailMessage],
) -> EmailChangeRequest:
    """
    An unconfirmed change request from alice to `new_email`.

    The outbox is cleared afterwards, so a test sees only the email its
    own action sends.
    """
    response = auth_client.post(CHANGE_EMAIL_URL, {"new_email": new_email})
    assert response.status_code == status.HTTP_201_CREATED
    mailoutbox.clear()
    return EmailChangeRequest.objects.get(user=alice)


####################################################################
#
@pytest.fixture
def confirmed_ecr(
    pending_ecr: EmailChangeRequest,
    auth_client: APIClient,
    mailoutbox: list[EmailMessage],
) -> EmailChangeRequest:
    """`pending_ecr`, confirmed: the revocation window is now open."""
    response = auth_client.post(_confirm_url(pending_ecr.token))
    assert response.status_code == status.HTTP_200_OK
    mailoutbox.clear()
    pending_ecr.refresh_from_db()
    assert pending_ecr.revocable_until is not None
    return pending_ecr


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
        old_email: str,
        new_email: str,
        mailoutbox: list[EmailMessage],
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

        response = auth_client.post(CHANGE_EMAIL_URL, {"new_email": new_email})

        assert response.status_code == status.HTTP_201_CREATED
        ecr = EmailChangeRequest.objects.get(user=alice)
        check.equal(ecr.old_email, old_email, "records the old address")
        check.equal(ecr.new_email, new_email, "records the new address")
        check.is_none(ecr.confirmed_at, "not confirmed")
        check.is_none(ecr.revoked_at, "not revoked")
        check.is_none(ecr.revocable_until, "no revocation window yet")
        check.is_false(ecr.is_expired, "not expired")

        alice.refresh_from_db()
        check.equal(alice.email, old_email, "address unchanged")
        check.equal(
            [m.to for m in mailoutbox],
            [[new_email]],
            "one verification email, to the new address",
        )
        check.is_true(
            Notification.objects.filter(
                user=alice, kind=EMAIL_CHANGE_REQUESTED
            ).exists(),
            "old address notified via the notification system",
        )
        check.is_true(session_valid(rt_a), "existing session unaffected")

    ####################################################################
    #
    def test_step2_confirm_updates_email_and_opens_window(
        self,
        alice: User,
        auth_client: APIClient,
        pending_ecr: EmailChangeRequest,
        new_email: str,
        mailoutbox: list[EmailMessage],
    ) -> None:
        """
        GIVEN: a pending EmailChangeRequest; RT-A held
        WHEN:  POST confirm/
        THEN:  200; User.email = new_email; confirmed_at + revocable_until set;
               no additional emails; RT-A still valid (confirmation does not
               invalidate sessions -- only revocation does)
        """
        rt_a = RefreshToken.for_user(alice)

        response = auth_client.post(_confirm_url(pending_ecr.token))

        assert response.status_code == status.HTTP_200_OK
        alice.refresh_from_db()
        pending_ecr.refresh_from_db()
        check.equal(alice.email, new_email, "address changed")
        check.equal(alice.username, new_email, "username follows it")
        assert pending_ecr.confirmed_at is not None
        assert pending_ecr.revocable_until is not None
        check.greater(
            pending_ecr.revocable_until,
            pending_ecr.confirmed_at,
            "revocation window opens",
        )
        check.equal(len(mailoutbox), 0, "confirmation itself sends no email")
        check.is_true(session_valid(rt_a), "existing session unaffected")

    ####################################################################
    #
    def test_step3_new_request_blocked_during_revocation_window(
        self,
        alice: User,
        auth_client: APIClient,
        confirmed_ecr: EmailChangeRequest,
        faker: Faker,
        mailoutbox: list[EmailMessage],
    ) -> None:
        """
        GIVEN: a confirmed EmailChangeRequest within its revocation window
        WHEN:  POST change-email again
        THEN:  409; no second request created; no emails sent
        """
        response = auth_client.post(
            CHANGE_EMAIL_URL, {"new_email": faker.unique.email()}
        )

        check.equal(response.status_code, status.HTTP_409_CONFLICT, "refused")
        check.equal(
            EmailChangeRequest.objects.filter(user=alice).count(),
            1,
            "no second request",
        )
        check.equal(len(mailoutbox), 0, "no email sent")

    ####################################################################
    #
    def test_step4_new_request_allowed_after_window_closes(
        self,
        alice: User,
        confirmed_ecr: EmailChangeRequest,
        make_auth_client: Callable[[User], APIClient],
        faker: Faker,
    ) -> None:
        """
        GIVEN: a confirmed EmailChangeRequest past its revocation window
        WHEN:  POST change-email
        THEN:  201 (lockout lifted)
        """
        assert confirmed_ecr.revocable_until is not None
        past_window = confirmed_ecr.revocable_until + timedelta(seconds=1)
        with freeze_time(past_window):
            alice.refresh_from_db()
            response = make_auth_client(alice).post(
                CHANGE_EMAIL_URL, {"new_email": faker.unique.email()}
            )

        assert response.status_code == status.HTTP_201_CREATED

    ####################################################################
    # Edge cases
    ####################################################################

    ####################################################################
    #
    def test_no_usable_password_returns_403(
        self, alice: User, auth_client: APIClient, new_email: str
    ) -> None:
        """
        GIVEN: a user with no usable password set
        WHEN:  POST change-email
        THEN:  403
        """
        alice.set_unusable_password()
        alice.save()

        response = auth_client.post(CHANGE_EMAIL_URL, {"new_email": new_email})

        assert response.status_code == status.HTTP_403_FORBIDDEN

    ####################################################################
    #
    def test_new_email_already_taken_returns_409(
        self,
        alice: User,
        auth_client: APIClient,
        user_factory: Callable[..., User],
        new_email: str,
        mailoutbox: list[EmailMessage],
    ) -> None:
        """
        GIVEN: new_email already belongs to another account
        WHEN:  POST change-email
        THEN:  409; no request created; no email sent
        """
        user_factory(email=new_email)

        response = auth_client.post(CHANGE_EMAIL_URL, {"new_email": new_email})

        check.equal(response.status_code, status.HTTP_409_CONFLICT, "refused")
        check.is_false(
            EmailChangeRequest.objects.filter(user=alice).exists(),
            "no request created",
        )
        check.equal(len(mailoutbox), 0, "no email sent")

    ####################################################################
    #
    def test_expired_token_returns_400(
        self,
        alice: User,
        auth_client: APIClient,
        pending_ecr: EmailChangeRequest,
        old_email: str,
    ) -> None:
        """
        GIVEN: a verification token that has passed its 24-hour expiry
        WHEN:  POST confirm/
        THEN:  400; User.email unchanged
        """
        past_expiry = pending_ecr.expires_at + timedelta(seconds=1)
        with freeze_time(past_expiry):
            response = auth_client.post(_confirm_url(pending_ecr.token))

        alice.refresh_from_db()
        check.equal(
            response.status_code, status.HTTP_400_BAD_REQUEST, "refused"
        )
        check.equal(alice.email, old_email, "address unchanged")

    ####################################################################
    #
    def test_already_confirmed_token_returns_400(
        self, auth_client: APIClient, confirmed_ecr: EmailChangeRequest
    ) -> None:
        """
        GIVEN: a token that has already been confirmed
        WHEN:  POST confirm/ a second time
        THEN:  400
        """
        response = auth_client.post(_confirm_url(confirmed_ecr.token))

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    ####################################################################
    #
    def test_email_taken_at_confirm_time_returns_409(
        self,
        alice: User,
        auth_client: APIClient,
        pending_ecr: EmailChangeRequest,
        user_factory: Callable[..., User],
        old_email: str,
    ) -> None:
        """
        GIVEN: new_email claimed by another account between request and confirm
        WHEN:  POST confirm/
        THEN:  409; User.email unchanged (race condition is caught at confirm time)
        """
        user_factory(email=pending_ecr.new_email)  # registers it first

        response = auth_client.post(_confirm_url(pending_ecr.token))

        alice.refresh_from_db()
        check.equal(response.status_code, status.HTTP_409_CONFLICT, "refused")
        check.equal(alice.email, old_email, "address unchanged")

    ####################################################################
    #
    def test_revoke_after_window_closed_returns_400(
        self, auth_client: APIClient, confirmed_ecr: EmailChangeRequest
    ) -> None:
        """
        GIVEN: a confirmed EmailChangeRequest past its revocation window
        WHEN:  POST revoke/
        THEN:  400 (the change is now permanent)
        """
        assert confirmed_ecr.revocable_until is not None
        past_window = confirmed_ecr.revocable_until + timedelta(seconds=1)
        with freeze_time(past_window):
            response = auth_client.post(_revoke_url(confirmed_ecr.token))

        assert response.status_code == status.HTTP_400_BAD_REQUEST


########################################################################
########################################################################
#
class TestFlowB1:
    """Flow B sub-case 1: revoked before confirmation.

    The request was caught early -- the email was never changed, but
    whoever requested it was signed in, so every session ends.
    """

    ####################################################################
    #
    def test_pre_confirmation_revocation(
        self,
        alice: User,
        auth_client: APIClient,
        old_email: str,
        new_email: str,
        faker: Faker,
        mailoutbox: list[EmailMessage],
    ) -> None:
        """
        GIVEN: a pending (unconfirmed) EmailChangeRequest to an attacker's
               address; RT-A and RT-B held
        WHEN:  POST revoke/
        THEN:  200; User.email unchanged; RT-A and RT-B both invalid;
               security alert sent to both old and new addresses;
               a new change request is immediately allowed
        """
        # Sessions are minted before the request, so `pending_ecr` is
        # not used here.
        #
        rt_a = RefreshToken.for_user(alice)
        rt_b = RefreshToken.for_user(alice)
        auth_client.post(CHANGE_EMAIL_URL, {"new_email": new_email})
        ecr = EmailChangeRequest.objects.get(user=alice)
        mailoutbox.clear()

        response = auth_client.post(_revoke_url(ecr.token))

        assert response.status_code == status.HTTP_200_OK
        ecr.refresh_from_db()
        alice.refresh_from_db()
        check.is_not_none(ecr.revoked_at, "request revoked")
        check.is_none(ecr.confirmed_at, "and never confirmed")
        check.equal(alice.email, old_email, "address unchanged")
        check.is_false(session_valid(rt_a), "session A killed")
        check.is_false(session_valid(rt_b), "session B killed")
        check.is_true(
            _sent_to(mailoutbox, new_email),
            "security alert emailed to the attacker's address",
        )
        check.is_true(
            Notification.objects.filter(
                user=alice, kind=EMAIL_CHANGE_SECURITY_ALERT
            ).exists(),
            "security alert queued for alice's address",
        )

        # No lockout: revocable_until was never set.
        again = auth_client.post(
            CHANGE_EMAIL_URL, {"new_email": faker.unique.email()}
        )
        check.equal(
            again.status_code, status.HTTP_201_CREATED, "new request allowed"
        )


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
        old_email: str,
        new_email: str,
        faker: Faker,
        mailoutbox: list[EmailMessage],
    ) -> None:
        """
        GIVEN: a confirmed EmailChangeRequest to an attacker's address,
               within its revocation window; RT-A (alice) and RT-B
               (attacker) both held
        WHEN:  POST revoke/ at confirmed_at + 3 days
        THEN:  200; User.email reverted; RT-A and RT-B both invalid;
               security alert sent to both addresses;
               second revoke returns 400;
               new request immediately allowed
        """
        # Sessions are minted before the request, so `confirmed_ecr` is
        # not used here.
        #
        rt_a = RefreshToken.for_user(alice)
        rt_b = RefreshToken.for_user(alice)
        auth_client.post(CHANGE_EMAIL_URL, {"new_email": new_email})
        ecr = EmailChangeRequest.objects.get(user=alice)
        auth_client.post(_confirm_url(ecr.token))

        alice.refresh_from_db()
        assert alice.email == new_email
        # Both sessions remain valid immediately after confirmation
        assert session_valid(rt_a)
        assert session_valid(rt_b)

        ecr.refresh_from_db()
        assert ecr.confirmed_at is not None
        three_days_later = ecr.confirmed_at + timedelta(days=3)
        mailoutbox.clear()

        with freeze_time(three_days_later):
            response = auth_client.post(_revoke_url(ecr.token))

        assert response.status_code == status.HTTP_200_OK
        alice.refresh_from_db()
        ecr.refresh_from_db()
        check.equal(alice.email, old_email, "address reverted")
        check.equal(alice.username, old_email, "username reverted")
        check.is_not_none(ecr.revoked_at, "request revoked")
        check.is_false(session_valid(rt_a), "session A killed")
        check.is_false(session_valid(rt_b), "session B killed")
        check.is_true(
            _sent_to(mailoutbox, new_email),
            "security alert emailed to the attacker's address",
        )
        check.is_true(
            Notification.objects.filter(
                user=alice, kind=EMAIL_CHANGE_SECURITY_ALERT
            ).exists(),
            "security alert queued for alice's restored address",
        )
        check.equal(
            auth_client.post(_revoke_url(ecr.token)).status_code,
            status.HTTP_400_BAD_REQUEST,
            "revoking again is refused",
        )
        check.equal(
            auth_client.post(
                CHANGE_EMAIL_URL, {"new_email": faker.unique.email()}
            ).status_code,
            status.HTTP_201_CREATED,
            "a new request is allowed at once",
        )

    ####################################################################
    #
    def test_login_with_old_credentials_succeeds_after_revocation(
        self,
        auth_client: APIClient,
        confirmed_ecr: EmailChangeRequest,
        client: Client,
        old_email: str,
        known_password: str,
    ) -> None:
        """
        GIVEN: a revoked post-confirmation email change
        WHEN:  login attempt with alice's original email and password
        THEN:  200 with access token (account fully usable under restored address)
        """
        auth_client.post(_revoke_url(confirmed_ecr.token))

        response = client.post(
            TOKEN_OBTAIN_URL,
            {"email": old_email, "password": known_password},
            content_type="application/json",
        )

        check.equal(response.status_code, status.HTTP_200_OK, "login works")
        check.is_in("access", response.json(), "and issues an access token")


####################################################################
#
@pytest.fixture
def ecr(request: pytest.FixtureRequest) -> EmailChangeRequest:
    """The change request named by the indirect parametrize."""
    return request.getfixturevalue(request.param)


########################################################################
########################################################################
#
class TestRevocationRecovery:
    """Revocation as takeover recovery: API keys and password changes."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "ecr,keys_revoked",
        [("pending_ecr", False), ("confirmed_ecr", True)],
        ids=["before-confirmation", "after-confirmation"],
        indirect=["ecr"],
    )
    def test_revocation_revokes_api_keys_once_confirmed(
        self,
        auth_client: APIClient,
        api_keys_in_every_state: dict[str, APIKey],
        ecr: EmailChangeRequest,
        keys_revoked: bool,
    ) -> None:
        """
        GIVEN: an email change request, pending or confirmed, and an
               active API key
        WHEN:  the request is revoked
        THEN:  the API key is revoked only if the change had been
               confirmed (the account was taken over); the security
               alert says how many keys went and lists the ones still
               active for review
        """
        response = auth_client.post(_revoke_url(ecr.token))

        assert response.status_code == status.HTTP_200_OK
        active = api_keys_in_every_state["active"]
        active.refresh_from_db()
        alert = Notification.objects.get(
            user=ecr.user, kind=EMAIL_CHANGE_SECURITY_ALERT
        )
        check.equal(active.is_revoked, keys_revoked, "API key revoked")
        check.equal(
            alert.context["revoked_api_keys"],
            int(keys_revoked),
            "alert counts the revoked key",
        )
        check.equal(
            [k["name"] for k in alert.context["api_keys"]],
            [] if keys_revoked else [active.name],
            "alert lists the keys still active",
        )

    ####################################################################
    #
    @pytest.mark.parametrize(
        "active_keys,lists_keys",
        [(2, True), (0, False)],
        ids=["with-keys", "no-keys"],
        indirect=["active_keys"],
    )
    def test_unconfirmed_alert_asks_owner_to_review_keys(
        self,
        auth_client: APIClient,
        active_keys: list[APIKey],
        pending_ecr: EmailChangeRequest,
        old_email: str,
        mailoutbox: list[EmailMessage],
        lists_keys: bool,
    ) -> None:
        """
        GIVEN: a pending email change, with or without active API keys
        WHEN:  the request is revoked and the owner's alert is sent
        THEN:  the alert asks the owner to review their API keys and
               names each one, only when there are any
        """
        auth_client.post(_revoke_url(pending_ecr.token))
        mailoutbox.clear()

        EmailChannel().send(
            Notification.objects.get(
                user=pending_ecr.user, kind=EMAIL_CHANGE_SECURITY_ALERT
            )
        )

        assert [m.to for m in mailoutbox] == [[old_email]]
        body = mailoutbox[0].body
        check.equal(
            "Revoke any you do not recognise" in body, lists_keys, "asks"
        )
        check.equal(
            [key.name in body for key in active_keys],
            [True] * len(active_keys),
            "names every active key",
        )

    ####################################################################
    #
    def test_password_change_keeps_revocation_link(
        self,
        auth_client: APIClient,
        confirmed_ecr: EmailChangeRequest,
        known_password: str,
        old_email: str,
    ) -> None:
        """
        GIVEN: a confirmed email change to an attacker's address
        WHEN:  the attacker, who knows the password, changes it, and
               the owner then follows the revocation link
        THEN:  the revocation still restores the owner's address
        """
        new_password = "an-attacker-chose-this-one-42!"
        changed = auth_client.post(
            reverse("api_v1:user-change-password"),
            {
                "current_password": known_password,
                "new_password": new_password,
                "confirm_password": new_password,
            },
        )
        assert changed.status_code == status.HTTP_204_NO_CONTENT

        response = auth_client.post(_revoke_url(confirmed_ecr.token))

        confirmed_ecr.user.refresh_from_db()
        check.equal(response.status_code, status.HTTP_200_OK, "revoked")
        check.equal(confirmed_ecr.user.email, old_email, "address restored")
