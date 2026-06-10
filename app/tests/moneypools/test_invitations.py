#!/usr/bin/env python
#
"""
Tests for the bank-account co-ownership invitation feature.

Covers:
  - Service layer: create, cancel, accept, decline
  - API endpoints: POST invite, GET invitations, POST cancel, public detail/accept/decline
  - Django acceptance page: GET and POST flows
  - Edge cases: expired token, double-action, non-owner, multi-invitation page
"""

# system imports
#
from collections.abc import Callable
from datetime import timedelta
from unittest.mock import MagicMock, patch

# 3rd party imports
#
import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from rest_framework import status
from rest_framework.test import APIClient

# Project imports
#
# Direct imports needed here because @pytest.mark.parametrize arguments
# are evaluated before pytest fixtures are resolved.
from moneypools.models import BankAccount, BankAccountInvitation
from moneypools.service import invitation as invitation_svc
from users.models import User

pytestmark = pytest.mark.django_db


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


def _my_invitations_url() -> str:
    return reverse("api_v1:user-my-invitations")


########################################################################
# Shared fixtures
########################################################################


@pytest.fixture(autouse=True)
def invitation_settings(settings) -> None:
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.SITE_URL = "http://testserver"
    settings.SITE_DISPLAY_NAME = "MiBudge [test]"
    settings.SUPPORT_EMAIL = "support@test.example.com"
    settings.INVITATION_EXPIRY_DAYS = 7


@pytest.fixture
def owner(user_factory: Callable[..., User]) -> User:
    return user_factory(email="owner@example.com")


@pytest.fixture
def other_owner(user_factory: Callable[..., User]) -> User:
    return user_factory(email="other@example.com")


@pytest.fixture
def account(
    bank_account_factory: Callable[..., BankAccount], owner: User
) -> BankAccount:
    return bank_account_factory(owners=[owner])


@pytest.fixture
def auth_client(owner: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=owner)
    return client


########################################################################
########################################################################
#
class TestCreateInvitation:
    """Service: create_invitation() happy paths and rejections."""

    ####################################################################
    #
    def test_new_user_creates_inactive_user_and_sends_email(
        self,
        account: BankAccount,
        owner: User,
        mock_send_notification_now: MagicMock,
    ) -> None:
        """
        GIVEN: an account with one owner, an email not yet in the system
        WHEN:  create_invitation() is called
        THEN:  a pending BankAccountInvitation is created;
               an inactive User is created for the invitee;
               one invitation email is sent to invitee_email
        """
        inv = invitation_svc.create_invitation(
            account, owner, "newperson@example.com"
        )

        assert inv.status == BankAccountInvitation.Status.PENDING
        assert inv.invitee_email == "newperson@example.com"
        assert inv.invitee_user is not None
        assert not inv.invitee_user.is_active
        assert not inv.invitee_user.has_usable_password()
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["newperson@example.com"]

    ####################################################################
    #
    def test_existing_user_reuses_user_record(
        self,
        account: BankAccount,
        owner: User,
        user_factory: Callable[..., User],
        mock_send_notification_now: MagicMock,
    ) -> None:
        """
        GIVEN: an account; an existing active user with a password
        WHEN:  create_invitation() targets the existing user's email
        THEN:  invitation created; no new User created; email sent
        """
        existing = user_factory(email="existing@example.com")
        initial_user_count = User.objects.count()

        inv = invitation_svc.create_invitation(
            account, owner, "existing@example.com"
        )

        assert inv.invitee_user == existing
        assert User.objects.count() == initial_user_count
        assert len(mail.outbox) == 1

    ####################################################################
    #
    def test_rejects_already_owner(
        self, account: BankAccount, owner: User, other_owner: User
    ) -> None:
        """
        GIVEN: a user who is already an owner of the account
        WHEN:  create_invitation() targets their email
        THEN:  InviteeAlreadyOwnerError raised; no invitation created
        """
        account.owners.add(other_owner)

        with pytest.raises(invitation_svc.InviteeAlreadyOwnerError):
            invitation_svc.create_invitation(account, owner, other_owner.email)

        assert BankAccountInvitation.objects.count() == 0

    ####################################################################
    #
    def test_rejects_duplicate_pending_invitation(
        self,
        account: BankAccount,
        owner: User,
        mock_send_notification_now: MagicMock,
    ) -> None:
        """
        GIVEN: a pending invitation already exists for an email + account
        WHEN:  create_invitation() targets the same email + account
        THEN:  InvitationAlreadyPendingError raised
        """
        invitation_svc.create_invitation(account, owner, "dup@example.com")
        mail.outbox.clear()

        with pytest.raises(invitation_svc.InvitationAlreadyPendingError):
            invitation_svc.create_invitation(account, owner, "dup@example.com")

    ####################################################################
    #
    def test_allows_new_invitation_after_expiry(
        self,
        account: BankAccount,
        owner: User,
        mock_send_notification_now: MagicMock,
    ) -> None:
        """
        GIVEN: a previous invitation for an email that has now expired
        WHEN:  create_invitation() targets the same email
        THEN:  a new invitation is created without error
        """
        with freeze_time(timezone.now() - timedelta(days=8)):
            invitation_svc.create_invitation(
                account, owner, "retry@example.com"
            )
        mail.outbox.clear()

        inv2 = invitation_svc.create_invitation(
            account, owner, "retry@example.com"
        )
        assert inv2.status == BankAccountInvitation.Status.PENDING


########################################################################
########################################################################
#
class TestCancelInvitation:
    """Service: cancel_invitation()."""

    ####################################################################
    #
    def test_cancels_pending_invitation(
        self,
        bank_account_invitation_factory: Callable[..., BankAccountInvitation],
        account: BankAccount,
        owner: User,
    ) -> None:
        """
        GIVEN: a pending invitation
        WHEN:  cancel_invitation() is called
        THEN:  status becomes cancelled; cancelled_at is set
        """
        inv = bank_account_invitation_factory(
            bank_account=account, invited_by=owner
        )
        invitation_svc.cancel_invitation(inv)

        inv.refresh_from_db()
        assert inv.status == BankAccountInvitation.Status.CANCELLED
        assert inv.cancelled_at is not None

    ####################################################################
    #
    @pytest.mark.parametrize(
        "terminal_status,exc_class",
        [
            (
                BankAccountInvitation.Status.ACCEPTED,
                invitation_svc.TokenAlreadyAcceptedError,
            ),
            (
                BankAccountInvitation.Status.DECLINED,
                invitation_svc.TokenAlreadyDeclinedError,
            ),
            (
                BankAccountInvitation.Status.CANCELLED,
                invitation_svc.TokenAlreadyCancelledError,
            ),
            (
                BankAccountInvitation.Status.EXPIRED,
                invitation_svc.TokenExpiredError,
            ),
        ],
    )
    def test_raises_on_terminal_status(
        self,
        terminal_status: str,
        exc_class: type,
        bank_account_invitation_factory: Callable[..., BankAccountInvitation],
        account: BankAccount,
    ) -> None:
        """
        GIVEN: an invitation already in a terminal state
        WHEN:  cancel_invitation() is called
        THEN:  the appropriate error is raised
        """
        inv = bank_account_invitation_factory(
            bank_account=account, status=terminal_status
        )
        with pytest.raises(exc_class):
            invitation_svc.cancel_invitation(inv)


########################################################################
########################################################################
#
class TestAcceptInvitation:
    """Service: accept_invitation()."""

    ####################################################################
    #
    def test_adds_existing_user_to_owners(
        self,
        bank_account_invitation_factory: Callable[..., BankAccountInvitation],
        account: BankAccount,
        owner: User,
        user_factory: Callable[..., User],
        mock_send_notification_now: MagicMock,
    ) -> None:
        """
        GIVEN: a pending invitation for an existing (active) user
        WHEN:  accept_invitation() is called
        THEN:  invitee added to account.owners; status = accepted; no password-reset email
        """
        invitee = user_factory(email="invitee@example.com")
        inv = bank_account_invitation_factory(
            bank_account=account,
            invited_by=owner,
            invitee_email=invitee.email,
            invitee_user=invitee,
        )

        invitation_svc.accept_invitation(inv.token)

        inv.refresh_from_db()
        assert inv.status == BankAccountInvitation.Status.ACCEPTED
        assert inv.accepted_at is not None
        assert account.owners.filter(pk=invitee.pk).exists()
        # No password-reset mail -- invitee already has a usable password
        assert len(mail.outbox) == 0

    ####################################################################
    #
    def test_new_user_gets_activated_and_password_reset_triggered(
        self,
        bank_account_invitation_factory: Callable[..., BankAccountInvitation],
        account: BankAccount,
        owner: User,
        user_factory: Callable[..., User],
        mock_send_notification_now: MagicMock,
    ) -> None:
        """
        GIVEN: a pending invitation for a brand-new (inactive, no-password) user
        WHEN:  accept_invitation() is called
        THEN:  user activated; added to owners; password-reset email dispatched
        """
        invitee = user_factory(email="brandnew@example.com")
        invitee.is_active = False
        invitee.set_unusable_password()
        invitee.save()

        inv = bank_account_invitation_factory(
            bank_account=account,
            invited_by=owner,
            invitee_email=invitee.email,
            invitee_user=invitee,
        )

        with patch(
            "moneypools.service.invitation.trigger_password_reset"
        ) as mock_reset:
            invitation_svc.accept_invitation(inv.token)

        mock_reset.assert_called_once_with(invitee, request=None)
        invitee.refresh_from_db()
        assert invitee.is_active
        assert account.owners.filter(pk=invitee.pk).exists()

    ####################################################################
    #
    def test_raises_on_wall_clock_expiry_marks_status(
        self,
        bank_account_invitation_factory: Callable[..., BankAccountInvitation],
        account: BankAccount,
    ) -> None:
        """
        GIVEN: a PENDING invitation whose expires_at is in the past
        WHEN:  accept_invitation() is called
        THEN:  TokenExpiredError raised; row status updated to EXPIRED as a side effect

        This is distinct from the terminal-status parametrize below: this
        exercises the wall-clock expiry branch in _validate_pending (status
        is still PENDING in the DB but the clock has passed expires_at),
        which also persists the EXPIRED status transition.
        """
        inv = bank_account_invitation_factory(
            bank_account=account,
            expires_at=timezone.now() - timedelta(hours=1),
        )
        with pytest.raises(invitation_svc.TokenExpiredError):
            invitation_svc.accept_invitation(inv.token)

        inv.refresh_from_db()
        assert inv.status == BankAccountInvitation.Status.EXPIRED

    ####################################################################
    #
    @pytest.mark.parametrize(
        "terminal_status,exc_class",
        [
            (
                BankAccountInvitation.Status.ACCEPTED,
                invitation_svc.TokenAlreadyAcceptedError,
            ),
            (
                BankAccountInvitation.Status.DECLINED,
                invitation_svc.TokenAlreadyDeclinedError,
            ),
            (
                BankAccountInvitation.Status.CANCELLED,
                invitation_svc.TokenAlreadyCancelledError,
            ),
            (
                BankAccountInvitation.Status.EXPIRED,
                invitation_svc.TokenExpiredError,
            ),
        ],
    )
    def test_raises_on_terminal_status(
        self,
        terminal_status: str,
        exc_class: type,
        bank_account_invitation_factory: Callable[..., BankAccountInvitation],
        account: BankAccount,
    ) -> None:
        """
        GIVEN: an invitation already in a terminal state
        WHEN:  accept_invitation() is called
        THEN:  the appropriate error is raised
        """
        inv = bank_account_invitation_factory(
            bank_account=account, status=terminal_status
        )
        with pytest.raises(exc_class):
            invitation_svc.accept_invitation(inv.token)

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
    def test_marks_declined(
        self,
        bank_account_invitation_factory: Callable[..., BankAccountInvitation],
        account: BankAccount,
        mock_send_notification_now: MagicMock,
    ) -> None:
        """
        GIVEN: a pending invitation
        WHEN:  decline_invitation() is called
        THEN:  status = declined; declined_at set; invitee NOT added to owners
        """
        inv = bank_account_invitation_factory(bank_account=account)
        invitation_svc.decline_invitation(inv.token)

        inv.refresh_from_db()
        assert inv.status == BankAccountInvitation.Status.DECLINED
        assert inv.declined_at is not None
        assert inv.invitee_user is not None
        assert not account.owners.filter(pk=inv.invitee_user.pk).exists()

    # Terminal-state and wall-clock-expiry error paths are wholly covered
    # by TestAcceptInvitation: both accept and decline delegate to the same
    # _validate_pending(), so testing it through one caller is sufficient.


########################################################################
########################################################################
#
class TestInviteAPI:
    """API: POST /api/v1/bank-accounts/{id}/invite/"""

    ####################################################################
    #
    def test_owner_can_invite(
        self,
        account: BankAccount,
        auth_client: APIClient,
        mock_send_notification_now: MagicMock,
    ) -> None:
        """
        GIVEN: an authenticated account owner
        WHEN:  POST invite with a new email
        THEN:  201; BankAccountInvitation created; email sent
        """
        response = auth_client.post(
            _invite_url(str(account.id)),
            {"invitee_email": "invited@example.com"},
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert BankAccountInvitation.objects.filter(
            bank_account=account, invitee_email="invited@example.com"
        ).exists()
        assert len(mail.outbox) == 1

    ####################################################################
    #
    def test_non_owner_cannot_invite(
        self,
        account: BankAccount,
        user_factory: Callable[..., User],
    ) -> None:
        """
        GIVEN: an authenticated user who does NOT own the account
        WHEN:  POST invite
        THEN:  403 or 404 (permission denied)
        """
        stranger = user_factory(email="stranger@example.com")
        client = APIClient()
        client.force_authenticate(user=stranger)

        response = client.post(
            _invite_url(str(account.id)),
            {"invitee_email": "target@example.com"},
        )

        assert response.status_code in (
            status.HTTP_403_FORBIDDEN,
            status.HTTP_404_NOT_FOUND,
        )

    ####################################################################
    #
    @pytest.mark.parametrize("conflict", ["already_owner", "duplicate_pending"])
    def test_returns_409_on_conflict(
        self,
        conflict: str,
        account: BankAccount,
        auth_client: APIClient,
        other_owner: User,
        mock_send_notification_now: MagicMock,
    ) -> None:
        """
        GIVEN: invitee_email already owns the account OR has a pending invitation
        WHEN:  POST invite
        THEN:  409 Conflict
        """
        if conflict == "already_owner":
            account.owners.add(other_owner)
            email = other_owner.email
        else:
            auth_client.post(
                _invite_url(str(account.id)),
                {"invitee_email": "dup@example.com"},
            )
            mail.outbox.clear()
            email = "dup@example.com"

        response = auth_client.post(
            _invite_url(str(account.id)), {"invitee_email": email}
        )
        assert response.status_code == status.HTTP_409_CONFLICT


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
        owner: User,
        auth_client: APIClient,
        bank_account_invitation_factory: Callable[..., BankAccountInvitation],
    ) -> None:
        inv = bank_account_invitation_factory(
            bank_account=account, invited_by=owner
        )
        response = auth_client.get(_invitations_url(str(account.id)))

        assert response.status_code == status.HTTP_200_OK
        ids = [item["id"] for item in response.data]
        assert str(inv.id) in ids

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
        bank_account_invitation_factory: Callable[..., BankAccountInvitation],
    ) -> None:
        bank_account_invitation_factory(
            bank_account=account, status=non_pending_status
        )
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
        owner: User,
        auth_client: APIClient,
        bank_account_invitation_factory: Callable[..., BankAccountInvitation],
    ) -> None:
        inv = bank_account_invitation_factory(
            bank_account=account, invited_by=owner
        )
        response = auth_client.post(_cancel_url(str(account.id), inv.token))

        assert response.status_code == status.HTTP_200_OK
        inv.refresh_from_db()
        assert inv.status == BankAccountInvitation.Status.CANCELLED

    ####################################################################
    #
    def test_non_sender_cannot_cancel(
        self,
        account: BankAccount,
        other_owner: User,
        bank_account_invitation_factory: Callable[..., BankAccountInvitation],
    ) -> None:
        account.owners.add(other_owner)
        inv = bank_account_invitation_factory(bank_account=account)
        client = APIClient()
        client.force_authenticate(user=other_owner)

        response = client.post(_cancel_url(str(account.id), inv.token))

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
        bank_account_invitation_factory: Callable[..., BankAccountInvitation],
        account: BankAccount,
    ) -> None:
        inv = bank_account_invitation_factory(bank_account=account)
        client = APIClient()  # unauthenticated

        response = client.get(_public_detail_url(inv.token))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["invitee_email"] == inv.invitee_email
        assert response.data["bank_account_name"] == account.name

    ####################################################################
    #
    def test_accept_via_api(
        self,
        bank_account_invitation_factory: Callable[..., BankAccountInvitation],
        account: BankAccount,
        user_factory: Callable[..., User],
        mock_send_notification_now: MagicMock,
    ) -> None:
        invitee = user_factory(email="api_invitee@example.com")
        inv = bank_account_invitation_factory(
            bank_account=account,
            invitee_email=invitee.email,
            invitee_user=invitee,
        )

        response = APIClient().post(_public_accept_url(inv.token))

        assert response.status_code == status.HTTP_200_OK
        assert account.owners.filter(pk=invitee.pk).exists()

    ####################################################################
    #
    def test_decline_via_api(
        self,
        bank_account_invitation_factory: Callable[..., BankAccountInvitation],
        account: BankAccount,
        mock_send_notification_now: MagicMock,
    ) -> None:
        inv = bank_account_invitation_factory(bank_account=account)

        response = APIClient().post(_public_decline_url(inv.token))

        assert response.status_code == status.HTTP_200_OK
        inv.refresh_from_db()
        assert inv.status == BankAccountInvitation.Status.DECLINED

    ####################################################################
    #
    def test_accept_expired_returns_400(
        self,
        bank_account_invitation_factory: Callable[..., BankAccountInvitation],
        account: BankAccount,
    ) -> None:
        inv = bank_account_invitation_factory(
            bank_account=account,
            expires_at=timezone.now() - timedelta(hours=1),
        )
        response = APIClient().post(_public_accept_url(inv.token))

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    ####################################################################
    #
    def test_detail_for_unknown_token_returns_404(self) -> None:
        response = APIClient().get(_public_detail_url("no-such-token"))
        assert response.status_code == status.HTTP_404_NOT_FOUND


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
        bank_account_invitation_factory: Callable[..., BankAccountInvitation],
        account: BankAccount,
        client,
    ) -> None:
        """
        GIVEN: a pending invitation
        WHEN:  GET /invitations/account/{token}/
        THEN:  200; page contains bank account name
        """
        inv = bank_account_invitation_factory(bank_account=account)

        response = client.get(_acceptance_page_url(inv.token))

        assert response.status_code == 200
        assert account.name.encode() in response.content

    ####################################################################
    #
    def test_get_unknown_token_shows_error(self, client) -> None:
        response = client.get(_acceptance_page_url("bad-token"))
        assert response.status_code == 200
        assert b"not found" in response.content.lower()

    ####################################################################
    #
    def test_post_accept_adds_owner(
        self,
        bank_account_invitation_factory: Callable[..., BankAccountInvitation],
        account: BankAccount,
        user_factory: Callable[..., User],
        client,
        mock_send_notification_now: MagicMock,
    ) -> None:
        """
        GIVEN: a pending invitation for an existing user
        WHEN:  POST action=accept to the acceptance page
        THEN:  200; invitee added to account.owners; result=accepted in context
        """
        invitee = user_factory(email="page_invitee@example.com")
        inv = bank_account_invitation_factory(
            bank_account=account,
            invitee_email=invitee.email,
            invitee_user=invitee,
        )

        response = client.post(
            _acceptance_page_url(inv.token), {"action": "accept"}
        )

        assert response.status_code == 200
        assert response.context["result"] == "accepted"
        assert account.owners.filter(pk=invitee.pk).exists()

    ####################################################################
    #
    def test_post_decline_marks_declined(
        self,
        bank_account_invitation_factory: Callable[..., BankAccountInvitation],
        account: BankAccount,
        client,
        mock_send_notification_now: MagicMock,
    ) -> None:
        inv = bank_account_invitation_factory(bank_account=account)

        response = client.post(
            _acceptance_page_url(inv.token), {"action": "decline"}
        )

        assert response.status_code == 200
        assert response.context["result"] == "declined"
        inv.refresh_from_db()
        assert inv.status == BankAccountInvitation.Status.DECLINED


########################################################################
########################################################################
#
class TestMultiInvitationPage:
    """Acceptance page lists all pending invitations for the same email."""

    ####################################################################
    #
    def test_page_shows_all_pending_for_email(
        self,
        bank_account_factory: Callable[..., BankAccount],
        bank_account_invitation_factory: Callable[..., BankAccountInvitation],
        owner: User,
        client,
    ) -> None:
        """
        GIVEN: two pending invitations for the same invitee email (different accounts)
        WHEN:  GET the acceptance page for one of them
        THEN:  200; both invitations appear in all_pending context
        """
        acct_a = bank_account_factory(owners=[owner])
        acct_b = bank_account_factory(owners=[owner])
        inv_a = bank_account_invitation_factory(
            bank_account=acct_a, invitee_email="multi@example.com"
        )
        bank_account_invitation_factory(
            bank_account=acct_b, invitee_email="multi@example.com"
        )

        response = client.get(_acceptance_page_url(inv_a.token))

        assert response.status_code == 200
        all_pending = response.context["all_pending"]
        assert len(all_pending) == 2
        assert all(i.invitee_email == "multi@example.com" for i in all_pending)


########################################################################
########################################################################
#
class TestMyInvitationsAPI:
    """API: GET /api/v1/users/me/invitations/"""

    ####################################################################
    #
    def test_returns_outgoing_pending_invitations(
        self,
        account: BankAccount,
        owner: User,
        auth_client: APIClient,
        bank_account_invitation_factory: Callable[..., BankAccountInvitation],
    ) -> None:
        inv = bank_account_invitation_factory(
            bank_account=account, invited_by=owner
        )
        response = auth_client.get(_my_invitations_url())

        assert response.status_code == status.HTTP_200_OK
        ids = [item["id"] for item in response.data]
        assert str(inv.id) in ids

    ####################################################################
    #
    def test_excludes_other_users_invitations(
        self,
        account: BankAccount,
        auth_client: APIClient,
        user_factory: Callable[..., User],
        bank_account_invitation_factory: Callable[..., BankAccountInvitation],
    ) -> None:
        other = user_factory(email="other_inviter@example.com")
        bank_account_invitation_factory(bank_account=account, invited_by=other)
        response = auth_client.get(_my_invitations_url())

        assert response.status_code == status.HTTP_200_OK
        assert response.data == []
