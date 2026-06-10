#!/usr/bin/env python
#
"""Tests for the user invitation acceptance page view."""

# system imports
#
from collections.abc import Callable
from datetime import UTC, datetime

# 3rd party imports
#
import pytest
from django.urls import reverse

# Project imports
#
from users.models import UserInvitation

pytestmark = pytest.mark.django_db

_PAST = datetime(2020, 1, 1, tzinfo=UTC)


def _invitation_url(token: str) -> str:
    return reverse("invitations:user-invitation", kwargs={"token": token})


########################################################################
########################################################################
#
class TestUserInvitationAcceptancePage:
    """Django template view: /invitations/user/{token}/

    The Django test client is unauthenticated by default, so every GET
    here also implicitly verifies that the page is reachable without auth.
    """

    ####################################################################
    #
    @pytest.mark.parametrize(
        "factory_kwargs,expected_error",
        [
            # Happy path: pending, not expired -- no error context
            ({}, None),
            # PENDING but wall-clock expired
            ({"expires_at": _PAST}, "expired"),
            # Terminal states
            ({"status": UserInvitation.Status.ACCEPTED}, "accepted"),
            ({"status": UserInvitation.Status.CANCELLED}, "cancelled"),
            ({"status": UserInvitation.Status.EXPIRED}, "expired"),
            # Token does not exist in the database
            (None, "not_found"),
        ],
    )
    def test_get_invitation_page(
        self,
        user_invitation_factory: Callable[..., UserInvitation],
        client,
        factory_kwargs: dict | None,
        expected_error: str | None,
    ) -> None:
        """
        GIVEN: an invitation in various states (or no invitation at all)
        WHEN:  GET /invitations/user/{token}/
        THEN:  200; error context matches expected state
        """
        if factory_kwargs is not None:
            inv = user_invitation_factory(**factory_kwargs)
            token = inv.token
        else:
            token = "no-such-token"

        response = client.get(_invitation_url(token))

        assert response.status_code == 200
        assert response.context.get("error") == expected_error

    ####################################################################
    #
    @pytest.mark.parametrize(
        "action,expected_result",
        [
            ("accept", "accepted"),
            ("bad_action", "bad_request"),
        ],
    )
    def test_post_invitation_page(
        self,
        user_invitation_factory: Callable[..., UserInvitation],
        client,
        action: str,
        expected_result: str,
    ) -> None:
        """
        GIVEN: a pending invitation
        WHEN:  POST with a given action value
        THEN:  200; result context matches expected outcome
        """
        # invitee_user=None skips trigger_password_reset in the service,
        # avoiding the need to mock allauth email sending in view tests.
        inv = user_invitation_factory(invitee_user=None)

        response = client.post(_invitation_url(inv.token), {"action": action})

        assert response.status_code == 200
        assert response.context["result"] == expected_result
