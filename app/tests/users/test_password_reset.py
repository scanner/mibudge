#!/usr/bin/env python
#
"""Test sessions and API-key review around allauth's password reset."""

# system imports
import re
from collections.abc import Callable
from unittest.mock import MagicMock

# 3rd party imports
import pytest
import pytest_check as check
from django.core.mail import EmailMessage
from django.test import Client
from django.urls import reverse
from rest_framework_simplejwt.tokens import RefreshToken

# Project imports
from notifications.channels.email import EmailChannel
from notifications.models import Notification
from tests.users.session_checks import session_valid
from users.models import APIKey, User
from users.notification_kinds import PASSWORD_CHANGED

pytestmark = pytest.mark.django_db

NEW_PASSWORD = "a-brand-new-passphrase-for-42!"


########################################################################
########################################################################
#
@pytest.fixture
def reset_user(request: pytest.FixtureRequest, user: User) -> User:
    """The user whose password is reset: `user`, an existing owner.

    Indirect-parametrize it with 'invitee' for a user who has no usable
    password yet (one who accepted an invitation).
    """
    if getattr(request, "param", "owner") == "invitee":
        user.set_unusable_password()
        user.save()
    return user


####################################################################
#
@pytest.fixture
def reset_link(
    reset_user: User, client: Client, mailoutbox: list[EmailMessage]
) -> str:
    """Request a reset for `reset_user` and return the emailed link's path.

    The outbox is cleared afterwards, so a test sees only the email its
    own action sends.
    """
    response = client.post(
        reverse("account_reset_password"), {"email": reset_user.email}
    )
    assert response.status_code == 302
    match = re.search(
        r"/accounts/password/reset/key/\S+/", str(mailoutbox[0].body)
    )
    assert match is not None
    mailoutbox.clear()
    return match.group(0)


####################################################################
#
@pytest.fixture
def complete_reset(
    reset_link: str, client: Client, mock_send_notification_now: MagicMock
) -> Callable[[], str]:
    """Return a callable that follows the reset link and sets a password.

    The callable returns the reset-complete page's path, where allauth
    redirects once the password is set.
    """

    def _complete() -> str:
        # allauth moves the key from the URL into the session and
        # redirects to the set-password form.
        form = client.get(reset_link)
        assert form.status_code == 302
        done = client.post(
            form["Location"],
            {"password1": NEW_PASSWORD, "password2": NEW_PASSWORD},
        )
        assert done.status_code == 302
        return done["Location"]

    return _complete


########################################################################
########################################################################
#
class TestPasswordReset:
    """Sessions and API-key review around a password reset."""

    ####################################################################
    #
    def test_request_ends_no_session(
        self, user: User, client: Client, mailoutbox: list[EmailMessage]
    ) -> None:
        """
        GIVEN: a signed-in user
        WHEN:  anyone requests a password reset for their address
        THEN:  the reset email goes out and the session keeps working
        """
        session = RefreshToken.for_user(user)

        response = client.post(
            reverse("account_reset_password"), {"email": user.email}
        )

        assert response.status_code == 302
        check.equal([m.to for m in mailoutbox], [[user.email]], "emailed")
        check.is_true(session_valid(session), "session still works")

    ####################################################################
    #
    def test_completion_ends_sessions_and_lists_active_keys(
        self,
        user: User,
        api_keys_in_every_state: dict[str, APIKey],
        complete_reset: Callable[[], str],
    ) -> None:
        """
        GIVEN: a signed-in user with API keys that are active, revoked
               and expired
        WHEN:  a password reset is completed from the emailed link
        THEN:  the session ends, every API key keeps its state, and the
               notification lists only the active key
        """
        session = RefreshToken.for_user(user)

        complete_reset()

        notification = Notification.objects.get(
            user=user, kind=PASSWORD_CHANGED
        )
        active = api_keys_in_every_state["active"]
        active.refresh_from_db()
        check.is_false(session_valid(session), "session ended")
        check.is_true(active.is_active, "active key left active")
        check.is_true(notification.context["reset"], "marked as a reset")
        check.equal(
            [k["name"] for k in notification.context["api_keys"]],
            [active.name],
            "lists only the active key",
        )

    ####################################################################
    #
    @pytest.mark.parametrize(
        "active_keys,lists_keys",
        [(2, True), (0, False)],
        ids=["with-keys", "no-keys"],
        indirect=["active_keys"],
    )
    def test_email_asks_owner_to_review_keys(
        self,
        user: User,
        active_keys: list[APIKey],
        complete_reset: Callable[[], str],
        mailoutbox: list[EmailMessage],
        lists_keys: bool,
    ) -> None:
        """
        GIVEN: a user with or without active API keys
        WHEN:  a password reset is completed and its notification sent
        THEN:  the email asks the owner to review their API keys and
               names each one, only when there are any
        """
        complete_reset()
        mailoutbox.clear()

        EmailChannel().send(
            Notification.objects.get(user=user, kind=PASSWORD_CHANGED)
        )

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
    @pytest.mark.parametrize("reset_user", ["invitee"], indirect=True)
    def test_first_password_sends_no_notification(
        self, reset_user: User, complete_reset: Callable[[], str]
    ) -> None:
        """
        GIVEN: an invitee with no usable password yet
        WHEN:  they set their first password through the reset link
        THEN:  no "password reset" notification is created
        """
        complete_reset()

        reset_user.refresh_from_db()
        assert reset_user.has_usable_password()
        assert not Notification.objects.filter(
            user=reset_user, kind=PASSWORD_CHANGED
        ).exists()

    ####################################################################
    #
    @pytest.mark.parametrize(
        "reset_user,heading",
        [("owner", "Change Password"), ("invitee", "Welcome to mibudge")],
        indirect=["reset_user"],
    )
    def test_complete_page_welcomes_first_password_once(
        self,
        reset_user: User,
        complete_reset: Callable[[], str],
        client: Client,
        heading: str,
    ) -> None:
        """
        GIVEN: an existing owner, or an invitee with no usable password
        WHEN:  they set a password through the reset link and land on
               the reset-complete page, then reload it
        THEN:  the owner sees the password-changed page; the invitee is
               welcomed, and a reload shows the password-changed page
        """
        done_page = complete_reset()

        first = client.get(done_page)
        reload = client.get(done_page)

        check.is_in(heading, first.content.decode(), "first visit")
        check.is_in(
            "Change Password", reload.content.decode(), "reload is generic"
        )
