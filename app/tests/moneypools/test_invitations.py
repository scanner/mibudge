#!/usr/bin/env python
#
"""
Tests for the bank-account co-ownership invitation feature.

Covers:
  - Service layer: create, cancel, accept, decline
  - API endpoints: POST invite, GET invitations, POST cancel, public detail/accept/decline
  - Django acceptance page: GET and POST flows
  - Edge cases: expired token, double-action, non-owner, multi-invitation page

The account owner sending the invitations is the default `user`, and
`account` is the bank account they own.
"""

# system imports
#
from collections.abc import Callable
from datetime import timedelta
from unittest.mock import MagicMock, call

# 3rd party imports
#
import pytest
import pytest_check as check
from django.core.mail import EmailMessage
from django.test import Client, RequestFactory
from django.urls import reverse
from django.utils import timezone
from faker import Faker
from freezegun import freeze_time
from pytest_django.fixtures import SettingsWrapper
from pytest_mock import MockerFixture
from rest_framework import status
from rest_framework.test import APIClient

# Project imports
#
from moneypools.models import BankAccount, BankAccountInvitation
from moneypools.service import invitation as invitation_svc
from users.models import User

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("site_email_settings", "invitation_limits"),
]


########################################################################
# URL helpers
########################################################################


def _invite_url(account_id: str) -> str:
    return reverse("api_v1:bankaccount-invite", kwargs={"id": account_id})


def _invitations_url(account_id: str) -> str:
    return reverse("api_v1:bankaccount-invitations", kwargs={"id": account_id})


def _cancel_url(account_id: str, token: str) -> str:
    return reverse(
        "api_v1:bankaccount-cancel-invitation",
        kwargs={"id": account_id, "token": token},
    )


def _public_detail_url(token: str) -> str:
    return reverse("api_v1:invitation-detail", kwargs={"token": token})


def _public_accept_url(token: str) -> str:
    return reverse("api_v1:invitation-accept", kwargs={"token": token})


def _public_decline_url(token: str) -> str:
    return reverse("api_v1:invitation-decline", kwargs={"token": token})


def _acceptance_page_url(token: str) -> str:
    return reverse("invitations:account-invitation", kwargs={"token": token})


MY_INVITATIONS_URL = reverse("api_v1:user-my-invitations")


########################################################################
# Shared fixtures
########################################################################


####################################################################
#
@pytest.fixture
def invitee_email(faker: Faker) -> str:
    """An address not yet known to the system."""
    return faker.unique.email()


####################################################################
#
@pytest.fixture
def co_owner(account: BankAccount, user_factory: Callable[..., User]) -> User:
    """A second owner of `account` (who did not send the invitations)."""
    other = user_factory()
    account.owners.add(other)
    return other


####################################################################
#
@pytest.fixture
def new_invitee(user_factory: Callable[..., User]) -> User:
    """An inactive user with no usable password, as an invitation creates."""
    invitee = user_factory(is_active=False)
    invitee.set_unusable_password()
    invitee.save()
    return invitee


####################################################################
#
@pytest.fixture
def make_invitation(
    account: BankAccount,
    user: User,
    bank_account_invitation_factory: Callable[..., BankAccountInvitation],
) -> Callable[..., BankAccountInvitation]:
    """Return a factory for invitations to `account` sent by `user`.

    Returns:
        A callable `(invitee=None, **overrides) -> BankAccountInvitation`.
        `invitee` sets both the invitee user and the address the
        invitation was sent to; `overrides` pass through to the model
        factory.
    """

    def _make(
        invitee: User | None = None, **overrides: object
    ) -> BankAccountInvitation:
        if invitee is not None:
            overrides.update(invitee_email=invitee.email, invitee_user=invitee)
        overrides.setdefault("bank_account", account)
        overrides.setdefault("invited_by", user)
        return bank_account_invitation_factory(**overrides)

    return _make


####################################################################
#
@pytest.fixture
def exhausted_window(
    account: BankAccount,
    invitee_email: str,
    make_invitation: Callable[..., BankAccountInvitation],
) -> None:
    """Five recent invitations to `invitee_email` on `account` -- the cap."""
    for _ in range(5):
        make_invitation(
            invitee_email=invitee_email,
            status=BankAccountInvitation.Status.CANCELLED,
        )


####################################################################
#
@pytest.fixture
def mock_password_reset(mocker: MockerFixture) -> MagicMock:
    """Patch the password-reset trigger accept_invitation() fires."""
    return mocker.patch("moneypools.service.invitation.trigger_password_reset")


########################################################################
########################################################################
#
class TestCreateInvitation:
    """Service: create_invitation() happy paths and rejections."""

    ####################################################################
    #
    @pytest.mark.usefixtures("mock_send_notification_now")
    def test_new_user_creates_inactive_user_and_sends_email(
        self,
        account: BankAccount,
        user: User,
        invitee_email: str,
        mailoutbox: list[EmailMessage],
    ) -> None:
        """
        GIVEN: an account with one owner, an email not yet in the system
        WHEN:  create_invitation() is called
        THEN:  a pending BankAccountInvitation is created;
               an inactive User is created for the invitee;
               one invitation email is sent to invitee_email
        """
        inv = invitation_svc.create_invitation(account, user, invitee_email)

        check.equal(inv.status, BankAccountInvitation.Status.PENDING, "pending")
        check.equal(inv.invitee_email, invitee_email, "for the invitee")
        check.equal(
            [m.to for m in mailoutbox], [[invitee_email]], "one email sent"
        )
        assert inv.invitee_user is not None
        check.is_false(inv.invitee_user.is_active, "invitee user inactive")
        check.is_false(
            inv.invitee_user.has_usable_password(), "with no password"
        )

    ####################################################################
    #
    @pytest.mark.usefixtures("mock_send_notification_now")
    def test_existing_user_reuses_user_record(
        self,
        account: BankAccount,
        user: User,
        user_factory: Callable[..., User],
        mailoutbox: list[EmailMessage],
    ) -> None:
        """
        GIVEN: an account; an existing active user with a password
        WHEN:  create_invitation() targets the existing user's email
        THEN:  invitation created; no new User created; email sent
        """
        existing = user_factory()
        initial_user_count = User.objects.count()

        inv = invitation_svc.create_invitation(account, user, existing.email)

        check.equal(inv.invitee_user, existing, "invites the existing user")
        check.equal(User.objects.count(), initial_user_count, "no new user")
        check.equal(len(mailoutbox), 1, "email sent")

    ####################################################################
    #
    def test_rejects_already_owner(
        self, account: BankAccount, user: User, co_owner: User
    ) -> None:
        """
        GIVEN: a user who is already an owner of the account
        WHEN:  create_invitation() targets their email
        THEN:  InviteeAlreadyOwnerError raised; no invitation created
        """
        with pytest.raises(invitation_svc.InviteeAlreadyOwnerError):
            invitation_svc.create_invitation(account, user, co_owner.email)

        assert BankAccountInvitation.objects.count() == 0

    ####################################################################
    #
    @pytest.mark.usefixtures("mock_send_notification_now")
    def test_rejects_duplicate_pending_invitation(
        self, account: BankAccount, user: User, invitee_email: str
    ) -> None:
        """
        GIVEN: a pending invitation already exists for an email + account
        WHEN:  create_invitation() targets the same email + account
        THEN:  InvitationAlreadyPendingError raised
        """
        invitation_svc.create_invitation(account, user, invitee_email)

        with pytest.raises(invitation_svc.InvitationAlreadyPendingError):
            invitation_svc.create_invitation(account, user, invitee_email)

    ####################################################################
    #
    @pytest.mark.usefixtures("mock_send_notification_now")
    def test_allows_new_invitation_after_expiry(
        self, account: BankAccount, user: User, invitee_email: str
    ) -> None:
        """
        GIVEN: a previous invitation for an email that has now expired
        WHEN:  create_invitation() targets the same email
        THEN:  a new invitation is created without error
        """
        with freeze_time(timezone.now() - timedelta(days=8)):
            invitation_svc.create_invitation(account, user, invitee_email)

        inv2 = invitation_svc.create_invitation(account, user, invitee_email)
        assert inv2.status == BankAccountInvitation.Status.PENDING

    ####################################################################
    #
    @pytest.mark.usefixtures("exhausted_window")
    def test_rejects_when_rolling_window_exceeded(
        self, account: BankAccount, user: User, invitee_email: str
    ) -> None:
        """
        GIVEN: 5 invitations (any status) to the same email + account in
               the last 30 days
        WHEN:  create_invitation() targets the same email + account
        THEN:  InvitationWindowExceededError raised
        """
        with pytest.raises(invitation_svc.InvitationWindowExceededError):
            invitation_svc.create_invitation(account, user, invitee_email)

    ####################################################################
    #
    @pytest.mark.usefixtures("exhausted_window", "mock_send_notification_now")
    def test_window_count_is_scoped_per_account(
        self,
        user: User,
        invitee_email: str,
        bank_account_factory: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: 5 invitations to an email against one account, exhausting
               that account's window
        WHEN:  create_invitation() targets the same email on a second
               account, which has no invitations of its own
        THEN:  succeeds -- the rolling window is scoped per account, not
               globally per email (unlike the admin user-invitation flow,
               which is email-only)
        """
        other_account = bank_account_factory(owners=[user])

        inv = invitation_svc.create_invitation(
            other_account, user, invitee_email
        )
        assert inv.status == BankAccountInvitation.Status.PENDING


########################################################################
########################################################################
#
class TestCancelInvitation:
    """Service: cancel_invitation()."""

    ####################################################################
    #
    def test_cancels_pending_invitation(
        self, make_invitation: Callable[..., BankAccountInvitation]
    ) -> None:
        """
        GIVEN: a pending invitation
        WHEN:  cancel_invitation() is called
        THEN:  status becomes cancelled; cancelled_at is set
        """
        inv = make_invitation()

        invitation_svc.cancel_invitation(inv)

        inv.refresh_from_db()
        check.equal(
            inv.status, BankAccountInvitation.Status.CANCELLED, "cancelled"
        )
        check.is_not_none(inv.cancelled_at, "and records when")


########################################################################
########################################################################
#
class TestResendInvitation:
    """Service: resend_invitation() -- rate limit enforcement."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "starting_send_count",
        [
            # Ordinary resend, nowhere near the cap.
            1,
            # send_count=3 is exactly at max_resends -- the block fires
            # at send_count > 3, not >= 3, so this boundary case must
            # still succeed (confirming 3 resends / 4 emails total are
            # permitted).
            3,
        ],
    )
    def test_resend_increments_send_count_and_sends_email(
        self,
        starting_send_count: int,
        make_invitation: Callable[..., BankAccountInvitation],
        mailoutbox: list[EmailMessage],
    ) -> None:
        """
        GIVEN: a pending invitation with send_count within the resend cap
               and last_sent_at > 1 hour ago
        WHEN:  resend_invitation() is called
        THEN:  send_count is incremented by one; email sent
        """
        inv = make_invitation(
            send_count=starting_send_count,
            last_sent_at=timezone.now() - timedelta(hours=2),
        )

        invitation_svc.resend_invitation(inv)

        inv.refresh_from_db()
        check.equal(inv.send_count, starting_send_count + 1, "count bumped")
        check.equal(
            [m.to for m in mailoutbox],
            [[inv.invitee_email]],
            "email sent to the invitee",
        )

    ####################################################################
    #
    @pytest.mark.parametrize(
        "send_count,last_sent_minutes_ago,exc_class",
        [
            # send_count=4 exceeds max_resends=3; cooldown has passed
            (4, 120, invitation_svc.ResendLimitReachedError),
            # send_count within limit; last sent only 30 min ago (< 1 h cooldown)
            (1, 30, invitation_svc.ResendCooldownActiveError),
        ],
    )
    def test_raises_when_resend_is_blocked(
        self,
        send_count: int,
        last_sent_minutes_ago: int,
        exc_class: type,
        make_invitation: Callable[..., BankAccountInvitation],
        mailoutbox: list[EmailMessage],
    ) -> None:
        """
        GIVEN: a pending invitation that violates a rate-limit rule
        WHEN:  resend_invitation() is called
        THEN:  the appropriate rate-limit error is raised; no email sent
        """
        inv = make_invitation(
            send_count=send_count,
            last_sent_at=timezone.now()
            - timedelta(minutes=last_sent_minutes_ago),
        )

        with pytest.raises(exc_class):
            invitation_svc.resend_invitation(inv)

        assert len(mailoutbox) == 0


########################################################################
########################################################################
#
class TestAcceptInvitation:
    """Service: accept_invitation()."""

    ####################################################################
    #
    @pytest.mark.usefixtures("mock_send_notification_now")
    def test_adds_existing_user_to_owners(
        self,
        account: BankAccount,
        user_factory: Callable[..., User],
        make_invitation: Callable[..., BankAccountInvitation],
        mailoutbox: list[EmailMessage],
    ) -> None:
        """
        GIVEN: a pending invitation for an existing (active) user
        WHEN:  accept_invitation() is called
        THEN:  invitee added to account.owners; status = accepted; no
               password-reset email (the invitee already has a password)
        """
        invitee = user_factory()
        inv = make_invitation(invitee)

        invitation_svc.accept_invitation(inv.token)

        inv.refresh_from_db()
        check.equal(
            inv.status, BankAccountInvitation.Status.ACCEPTED, "accepted"
        )
        check.is_not_none(inv.accepted_at, "and records when")
        check.is_true(
            account.owners.filter(pk=invitee.pk).exists(), "invitee owns"
        )
        check.equal(len(mailoutbox), 0, "no password-reset email")

    ####################################################################
    #
    @pytest.mark.usefixtures("mock_send_notification_now")
    def test_new_user_gets_activated_and_password_reset_triggered(
        self,
        account: BankAccount,
        new_invitee: User,
        make_invitation: Callable[..., BankAccountInvitation],
        mock_password_reset: MagicMock,
    ) -> None:
        """
        GIVEN: a pending invitation for a brand-new (inactive, no-password) user
        WHEN:  accept_invitation() is called
        THEN:  user activated; added to owners; password-reset email dispatched
        """
        inv = make_invitation(new_invitee)

        invitation_svc.accept_invitation(inv.token)

        check.equal(
            mock_password_reset.call_args_list,
            [call(new_invitee, request=None)],
            "password reset triggered",
        )
        new_invitee.refresh_from_db()
        check.is_true(new_invitee.is_active, "invitee activated")
        check.is_true(
            account.owners.filter(pk=new_invitee.pk).exists(), "invitee owns"
        )

    ####################################################################
    #
    @pytest.mark.usefixtures("mock_send_notification_now")
    def test_new_user_password_reset_email_links_to_site_url(
        self,
        new_invitee: User,
        make_invitation: Callable[..., BankAccountInvitation],
        mailoutbox: list[EmailMessage],
        rf: RequestFactory,
        settings: SettingsWrapper,
    ) -> None:
        """
        GIVEN: a pending invitation for a brand-new user, accepted via a
               request whose Host header is an internal deployment name
               (proxies rewrite Host, so the public domain never reaches
               Django)
        WHEN:  accept_invitation() runs with that request
        THEN:  the set-your-first-password email links to SITE_URL, not
               to the request's internal host
        """
        settings.SITE_URL = "https://public.mibudge.test"
        settings.ALLOWED_HOSTS = ["internal.mibudge.test"]
        inv = make_invitation(new_invitee)
        request = rf.post("/", HTTP_HOST="internal.mibudge.test")

        invitation_svc.accept_invitation(inv.token, request=request)

        assert len(mailoutbox) == 1
        body = str(mailoutbox[0].body)
        check.is_in(
            "https://public.mibudge.test/accounts/password/reset/key/",
            body,
            "links to the public site",
        )
        check.is_not_in(
            "internal.mibudge.test", body, "not to the internal host"
        )

    ####################################################################
    #
    def test_raises_on_wall_clock_expiry_marks_status(
        self, make_invitation: Callable[..., BankAccountInvitation]
    ) -> None:
        """
        GIVEN: a PENDING invitation whose expires_at is in the past
        WHEN:  accept_invitation() is called
        THEN:  TokenExpiredError raised; row status updated to EXPIRED as a side effect

        This is distinct from the stored-EXPIRED case of
        `test_terminal_status_is_rejected`: this exercises the wall-clock
        expiry branch in _validate_pending (status is still PENDING in the
        DB but the clock has passed expires_at), which also persists the
        EXPIRED status transition.
        """
        inv = make_invitation(expires_at=timezone.now() - timedelta(hours=1))

        with pytest.raises(invitation_svc.TokenExpiredError):
            invitation_svc.accept_invitation(inv.token)

        inv.refresh_from_db()
        assert inv.status == BankAccountInvitation.Status.EXPIRED

    ####################################################################
    #
    def test_raises_on_unknown_token(self) -> None:
        """
        GIVEN: no invitation exists for a token
        WHEN:  accept_invitation() is called
        THEN:  TokenNotFoundError raised
        """
        with pytest.raises(invitation_svc.TokenNotFoundError):
            invitation_svc.accept_invitation("does-not-exist")


########################################################################
########################################################################
#
class TestDeclineInvitation:
    """Service: decline_invitation()."""

    ####################################################################
    #
    @pytest.mark.usefixtures("mock_send_notification_now")
    def test_marks_declined(
        self,
        account: BankAccount,
        make_invitation: Callable[..., BankAccountInvitation],
    ) -> None:
        """
        GIVEN: a pending invitation
        WHEN:  decline_invitation() is called
        THEN:  status = declined; declined_at set; invitee NOT added to owners
        """
        inv = make_invitation()

        invitation_svc.decline_invitation(inv.token)

        inv.refresh_from_db()
        check.equal(
            inv.status, BankAccountInvitation.Status.DECLINED, "declined"
        )
        check.is_not_none(inv.declined_at, "and records when")
        assert inv.invitee_user is not None
        check.is_false(
            account.owners.filter(pk=inv.invitee_user.pk).exists(),
            "invitee does not own",
        )

    # Terminal-state and wall-clock-expiry error paths are wholly covered
    # through accept: both accept and decline delegate to the same
    # _validate_pending(), so testing it through one caller is sufficient.


########################################################################
########################################################################
#
@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(invitation_svc.cancel_invitation, id="cancel"),
        pytest.param(invitation_svc.resend_invitation, id="resend"),
        pytest.param(
            lambda inv: invitation_svc.accept_invitation(inv.token),
            id="accept",
        ),
    ],
)
@pytest.mark.parametrize(
    "terminal_status,exc_class",
    [
        pytest.param(
            BankAccountInvitation.Status.ACCEPTED,
            invitation_svc.TokenAlreadyAcceptedError,
            id="accepted",
        ),
        pytest.param(
            BankAccountInvitation.Status.DECLINED,
            invitation_svc.TokenAlreadyDeclinedError,
            id="declined",
        ),
        pytest.param(
            BankAccountInvitation.Status.CANCELLED,
            invitation_svc.TokenAlreadyCancelledError,
            id="cancelled",
        ),
        pytest.param(
            BankAccountInvitation.Status.EXPIRED,
            invitation_svc.TokenExpiredError,
            id="expired",
        ),
    ],
)
def test_terminal_status_is_rejected(
    make_invitation: Callable[..., BankAccountInvitation],
    mailoutbox: list[EmailMessage],
    operation: Callable[[BankAccountInvitation], object],
    terminal_status: str,
    exc_class: type,
) -> None:
    """
    GIVEN: an invitation already in a terminal state
    WHEN:  it is cancelled, resent or accepted
    THEN:  the error for that state is raised; no email is sent

    For resend this also pins the ordering guarantee: _validate_pending()
    fires before check_resend(), so terminal-status short-circuits before
    any rate-limit evaluation (the factory default leaves last_sent_at
    within the cooldown window, so a wrong ordering would produce
    ResendCooldownActiveError instead).
    """
    inv = make_invitation(status=terminal_status)

    with pytest.raises(exc_class):
        operation(inv)

    assert len(mailoutbox) == 0


########################################################################
########################################################################
#
class TestInviteAPI:
    """API: POST /api/v1/bank-accounts/{id}/invite/"""

    ####################################################################
    #
    @pytest.mark.usefixtures("mock_send_notification_now")
    def test_owner_can_invite(
        self,
        account: BankAccount,
        auth_client: APIClient,
        invitee_email: str,
        mailoutbox: list[EmailMessage],
    ) -> None:
        """
        GIVEN: an authenticated account owner
        WHEN:  POST invite with a new email
        THEN:  201; BankAccountInvitation created; email sent
        """
        response = auth_client.post(
            _invite_url(str(account.id)), {"invitee_email": invitee_email}
        )

        assert response.status_code == status.HTTP_201_CREATED
        check.is_true(
            BankAccountInvitation.objects.filter(
                bank_account=account, invitee_email=invitee_email
            ).exists(),
            "invitation created",
        )
        check.equal(len(mailoutbox), 1, "email sent")

    ####################################################################
    #
    def test_non_owner_cannot_invite(
        self,
        account: BankAccount,
        invitee_email: str,
        user_factory: Callable[..., User],
        make_auth_client: Callable[[User], APIClient],
    ) -> None:
        """
        GIVEN: an authenticated user who does NOT own the account
        WHEN:  POST invite
        THEN:  404 -- the account is not in their queryset
        """
        client = make_auth_client(user_factory())

        response = client.post(
            _invite_url(str(account.id)), {"invitee_email": invitee_email}
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    ####################################################################
    #
    def test_existing_owner_returns_409(
        self, account: BankAccount, auth_client: APIClient, co_owner: User
    ) -> None:
        """
        GIVEN: invitee_email already owns the account
        WHEN:  POST invite
        THEN:  409 Conflict
        """
        response = auth_client.post(
            _invite_url(str(account.id)), {"invitee_email": co_owner.email}
        )

        assert response.status_code == status.HTTP_409_CONFLICT

    ####################################################################
    #
    def test_pending_invitation_returns_409(
        self,
        account: BankAccount,
        auth_client: APIClient,
        make_invitation: Callable[..., BankAccountInvitation],
        invitee_email: str,
    ) -> None:
        """
        GIVEN: invitee_email already has a pending invitation to the account
        WHEN:  POST invite
        THEN:  409 Conflict
        """
        make_invitation(invitee_email=invitee_email)

        response = auth_client.post(
            _invite_url(str(account.id)), {"invitee_email": invitee_email}
        )

        assert response.status_code == status.HTTP_409_CONFLICT

    ####################################################################
    #
    @pytest.mark.usefixtures("exhausted_window")
    def test_returns_429_when_rolling_window_exceeded(
        self, account: BankAccount, auth_client: APIClient, invitee_email: str
    ) -> None:
        """
        GIVEN: the rolling-window cap is exhausted for this email + account
        WHEN:  POST invite for the same email
        THEN:  429 Too Many Requests (not a 500)
        """
        response = auth_client.post(
            _invite_url(str(account.id)), {"invitee_email": invitee_email}
        )

        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert "Too many invitations" in response.data["detail"]


########################################################################
########################################################################
#
class TestInvitationsListAPI:
    """API: GET /api/v1/bank-accounts/{id}/invitations/"""

    ####################################################################
    #
    def test_lists_pending_invitations(
        self,
        account: BankAccount,
        auth_client: APIClient,
        make_invitation: Callable[..., BankAccountInvitation],
    ) -> None:
        """
        GIVEN: a pending invitation to the owner's account
        WHEN:  GET invitations
        THEN:  it is listed
        """
        inv = make_invitation()

        response = auth_client.get(_invitations_url(str(account.id)))

        assert response.status_code == status.HTTP_200_OK
        assert str(inv.id) in [item["id"] for item in response.data]

    ####################################################################
    #
    @pytest.mark.parametrize(
        "non_pending_status",
        [
            BankAccountInvitation.Status.ACCEPTED,
            BankAccountInvitation.Status.DECLINED,
            BankAccountInvitation.Status.CANCELLED,
        ],
    )
    def test_excludes_non_pending(
        self,
        non_pending_status: str,
        account: BankAccount,
        auth_client: APIClient,
        make_invitation: Callable[..., BankAccountInvitation],
    ) -> None:
        """
        GIVEN: an invitation to the owner's account that is no longer pending
        WHEN:  GET invitations
        THEN:  nothing is listed
        """
        make_invitation(status=non_pending_status)

        response = auth_client.get(_invitations_url(str(account.id)))

        assert response.status_code == status.HTTP_200_OK
        assert response.data == []


########################################################################
########################################################################
#
class TestCancelInvitationAPI:
    """API: POST /api/v1/bank-accounts/{id}/invitations/{token}/cancel/"""

    ####################################################################
    #
    def test_sender_can_cancel(
        self,
        account: BankAccount,
        auth_client: APIClient,
        make_invitation: Callable[..., BankAccountInvitation],
    ) -> None:
        """
        GIVEN: a pending invitation the owner sent
        WHEN:  the owner POSTs cancel
        THEN:  200; the invitation is cancelled
        """
        inv = make_invitation()

        response = auth_client.post(_cancel_url(str(account.id), inv.token))

        assert response.status_code == status.HTTP_200_OK
        inv.refresh_from_db()
        assert inv.status == BankAccountInvitation.Status.CANCELLED

    ####################################################################
    #
    def test_non_sender_cannot_cancel(
        self,
        account: BankAccount,
        co_owner: User,
        make_invitation: Callable[..., BankAccountInvitation],
        make_auth_client: Callable[[User], APIClient],
    ) -> None:
        """
        GIVEN: a pending invitation sent by the other owner
        WHEN:  a co-owner who did not send it POSTs cancel
        THEN:  403; the invitation stays pending
        """
        inv = make_invitation()

        response = make_auth_client(co_owner).post(
            _cancel_url(str(account.id), inv.token)
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        inv.refresh_from_db()
        assert inv.status == BankAccountInvitation.Status.PENDING


########################################################################
########################################################################
#
class TestPublicInvitationAPI:
    """API: public detail / accept / decline endpoints (AllowAny)."""

    ####################################################################
    #
    def test_detail_returns_invitation_info(
        self,
        account: BankAccount,
        api_client: APIClient,
        make_invitation: Callable[..., BankAccountInvitation],
    ) -> None:
        """
        GIVEN: a pending invitation
        WHEN:  an unauthenticated client GETs its public detail
        THEN:  200 with the invitee address and the account name
        """
        inv = make_invitation()

        response = api_client.get(_public_detail_url(inv.token))

        assert response.status_code == status.HTTP_200_OK
        check.equal(
            response.data["invitee_email"], inv.invitee_email, "invitee"
        )
        check.equal(
            response.data["bank_account_name"], account.name, "account name"
        )

    ####################################################################
    #
    def test_detail_for_unknown_token_returns_404(
        self, api_client: APIClient
    ) -> None:
        """
        GIVEN: no invitation for a token
        WHEN:  GET its public detail
        THEN:  404
        """
        response = api_client.get(_public_detail_url("no-such-token"))

        assert response.status_code == status.HTTP_404_NOT_FOUND

    ####################################################################
    #
    @pytest.mark.usefixtures("mock_send_notification_now")
    def test_accept_via_api(
        self,
        account: BankAccount,
        api_client: APIClient,
        user_factory: Callable[..., User],
        make_invitation: Callable[..., BankAccountInvitation],
    ) -> None:
        """
        GIVEN: a pending invitation for an existing user
        WHEN:  an unauthenticated client POSTs public accept
        THEN:  200; the invitee owns the account
        """
        invitee = user_factory()
        inv = make_invitation(invitee)

        response = api_client.post(_public_accept_url(inv.token))

        assert response.status_code == status.HTTP_200_OK
        assert account.owners.filter(pk=invitee.pk).exists()

    ####################################################################
    #
    @pytest.mark.usefixtures("mock_send_notification_now")
    def test_decline_via_api(
        self,
        api_client: APIClient,
        make_invitation: Callable[..., BankAccountInvitation],
    ) -> None:
        """
        GIVEN: a pending invitation
        WHEN:  an unauthenticated client POSTs public decline
        THEN:  200; the invitation is declined
        """
        inv = make_invitation()

        response = api_client.post(_public_decline_url(inv.token))

        assert response.status_code == status.HTTP_200_OK
        inv.refresh_from_db()
        assert inv.status == BankAccountInvitation.Status.DECLINED

    ####################################################################
    #
    def test_accept_expired_returns_400(
        self,
        api_client: APIClient,
        make_invitation: Callable[..., BankAccountInvitation],
    ) -> None:
        """
        GIVEN: a pending invitation past its expiry
        WHEN:  POST public accept
        THEN:  400
        """
        inv = make_invitation(expires_at=timezone.now() - timedelta(hours=1))

        response = api_client.post(_public_accept_url(inv.token))

        assert response.status_code == status.HTTP_400_BAD_REQUEST


########################################################################
########################################################################
#
class TestAcceptancePage:
    """Django template view: /invitations/account/{token}/

    The Django test client is unauthenticated by default, so every GET
    here also implicitly verifies that the page is reachable without auth.
    """

    ####################################################################
    #
    def test_get_renders_pending_invitation(
        self,
        account: BankAccount,
        client: Client,
        make_invitation: Callable[..., BankAccountInvitation],
    ) -> None:
        """
        GIVEN: a pending invitation
        WHEN:  GET /invitations/account/{token}/
        THEN:  200; page contains bank account name
        """
        inv = make_invitation()

        response = client.get(_acceptance_page_url(inv.token))

        assert response.status_code == 200
        assert account.name.encode() in response.content

    ####################################################################
    #
    def test_get_unknown_token_shows_error(self, client: Client) -> None:
        """
        GIVEN: no invitation for a token
        WHEN:  GET its acceptance page
        THEN:  200; the page says it was not found
        """
        response = client.get(_acceptance_page_url("bad-token"))

        assert response.status_code == 200
        assert b"not found" in response.content.lower()

    ####################################################################
    #
    @pytest.mark.usefixtures("mock_send_notification_now")
    def test_post_accept_adds_owner(
        self,
        account: BankAccount,
        client: Client,
        user_factory: Callable[..., User],
        make_invitation: Callable[..., BankAccountInvitation],
    ) -> None:
        """
        GIVEN: a pending invitation for an existing user
        WHEN:  POST action=accept to the acceptance page
        THEN:  200; invitee added to account.owners; result=accepted in context
        """
        invitee = user_factory()
        inv = make_invitation(invitee)

        response = client.post(
            _acceptance_page_url(inv.token), {"action": "accept"}
        )

        assert response.status_code == 200
        check.equal(response.context["result"], "accepted", "reports accepted")
        check.is_true(
            account.owners.filter(pk=invitee.pk).exists(), "invitee owns"
        )

    ####################################################################
    #
    @pytest.mark.usefixtures("mock_send_notification_now")
    def test_post_decline_marks_declined(
        self,
        client: Client,
        make_invitation: Callable[..., BankAccountInvitation],
    ) -> None:
        """
        GIVEN: a pending invitation
        WHEN:  POST action=decline to the acceptance page
        THEN:  200; result=declined in context; the invitation is declined
        """
        inv = make_invitation()

        response = client.post(
            _acceptance_page_url(inv.token), {"action": "decline"}
        )

        assert response.status_code == 200
        check.equal(response.context["result"], "declined", "reports declined")
        inv.refresh_from_db()
        check.equal(
            inv.status, BankAccountInvitation.Status.DECLINED, "declined"
        )

    ####################################################################
    #
    def test_page_shows_all_pending_for_email(
        self,
        bank_account_factory: Callable[..., BankAccount],
        user: User,
        invitee_email: str,
        client: Client,
        make_invitation: Callable[..., BankAccountInvitation],
    ) -> None:
        """
        GIVEN: two pending invitations for the same invitee email (different accounts)
        WHEN:  GET the acceptance page for one of them
        THEN:  200; both invitations appear in all_pending context
        """
        inv_a = make_invitation(invitee_email=invitee_email)
        make_invitation(
            invitee_email=invitee_email,
            bank_account=bank_account_factory(owners=[user]),
        )

        response = client.get(_acceptance_page_url(inv_a.token))

        assert response.status_code == 200
        all_pending = response.context["all_pending"]
        check.equal(len(all_pending), 2, "both invitations listed")
        check.is_true(
            all(i.invitee_email == invitee_email for i in all_pending),
            "all for the invitee",
        )


########################################################################
########################################################################
#
class TestMyInvitationsAPI:
    """API: GET /api/v1/users/me/invitations/"""

    ####################################################################
    #
    def test_returns_outgoing_pending_invitations(
        self,
        auth_client: APIClient,
        make_invitation: Callable[..., BankAccountInvitation],
    ) -> None:
        """
        GIVEN: a pending invitation the user sent
        WHEN:  GET my invitations
        THEN:  it is listed
        """
        inv = make_invitation()

        response = auth_client.get(MY_INVITATIONS_URL)

        assert response.status_code == status.HTTP_200_OK
        assert str(inv.id) in [item["id"] for item in response.data]

    ####################################################################
    #
    def test_excludes_other_users_invitations(
        self,
        auth_client: APIClient,
        user_factory: Callable[..., User],
        make_invitation: Callable[..., BankAccountInvitation],
    ) -> None:
        """
        GIVEN: a pending invitation to the user's account sent by someone else
        WHEN:  GET my invitations
        THEN:  nothing is listed
        """
        make_invitation(invited_by=user_factory())

        response = auth_client.get(MY_INVITATIONS_URL)

        assert response.status_code == status.HTTP_200_OK
        assert response.data == []
