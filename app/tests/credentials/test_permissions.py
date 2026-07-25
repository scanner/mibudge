#!/usr/bin/env python
#
"""Tests for the RequiresInteractiveAuth blocklist gate.

The gate is credential-agnostic by design: every machine credential --
API keys and OAuth2 access tokens alike -- must be denied on
user/security endpoints, and interactive JWT sessions must be
unaffected.  The endpoint matrix therefore lives here once and is
parametrized over credential kind rather than repeated per credential.
"""

# system imports
from collections.abc import Callable

# 3rd party imports
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

# Project imports
from users.models import User

from .conftest import MACHINE_CREDENTIAL_KINDS

pytestmark = pytest.mark.django_db


########################################################################
########################################################################
#
class TestRequiresInteractiveAuth:
    """Tests for the machine-credential blocklist gate."""

    ####################################################################
    #
    @pytest.mark.parametrize("kind", MACHINE_CREDENTIAL_KINDS)
    @pytest.mark.parametrize(
        "method,url_name,expected_status",
        [
            # Sensitive user/security endpoints: machine creds denied.
            ("patch", "api_v1:user-me", 403),
            ("post", "api_v1:user-change-password", 403),
            ("post", "api_v1:user-change-email", 403),
            ("get", "api_v1:user-my-invitations", 403),
            ("get", "api_v1:api-key-list", 403),
            ("post", "api_v1:api-key-list", 403),
            # Profile reads + budgeting domain: allowed.
            ("get", "api_v1:user-me", 200),
            ("get", "api_v1:bank-list", 200),
            ("get", "api_v1:bankaccount-list", 200),
        ],
    )
    def test_machine_credential_access_by_endpoint(
        self,
        user: User,
        credential_client: Callable[[str, User], APIClient],
        kind: str,
        method: str,
        url_name: str,
        expected_status: int,
    ):
        """
        GIVEN: a valid machine credential (API key or OAuth2 token)
        WHEN:  a v1 endpoint is accessed with it
        THEN:  user/security endpoints deny it with 403, while profile
               reads and budgeting-domain endpoints allow it
        """
        client = credential_client(kind, user)
        response = getattr(client, method)(reverse(url_name))
        assert response.status_code == expected_status

    ####################################################################
    #
    @pytest.mark.parametrize("kind", MACHINE_CREDENTIAL_KINDS + ["jwt"])
    def test_credential_can_read_own_profile(
        self,
        user: User,
        credential_client: Callable[[str, User], APIClient],
        kind: str,
    ):
        """
        GIVEN: any credential mibudge accepts
        WHEN:  GET /users/me/ is requested with it
        THEN:  it authenticates as that credential's user and returns
               the fields machine consumers rely on (the importers read
               the timezone), which is why this one user-domain read is
               exempted via RequiresInteractiveAuthForWrites
        """
        response = credential_client(kind, user).get(reverse("api_v1:user-me"))

        assert response.status_code == 200
        assert response.data["username"] == user.username
        assert response.data["timezone"] == user.timezone

    ####################################################################
    #
    def test_interactive_session_is_not_gated(
        self,
        user: User,
        credential_client: Callable[[str, User], APIClient],
    ):
        """
        GIVEN: a genuine JWT access token
        WHEN:  a gated user/security endpoint is requested with it
        THEN:  the request is allowed -- the gate must not mistake an
               interactive session for a machine credential, including
               now that OAuth2Authentication runs ahead of JWT on the
               same 'Bearer' scheme
        """
        client = credential_client("jwt", user)

        assert client.get(reverse("api_v1:api-key-list")).status_code == 200
