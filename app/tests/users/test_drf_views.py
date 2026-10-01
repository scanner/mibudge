"""Tests for the users DRF API views."""

# system imports
#
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

# 3rd party imports
#
import pytest
import pytest_check as check
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

# app imports
#
from tests.users.session_checks import session_valid
from users.api.v1.views import UserViewSet
from users.models import APIKey, User
from users.views import REFRESH_COOKIE_NAME

pytestmark = pytest.mark.django_db


########################################################################
########################################################################
#
class TestUserViewSet:
    """Tests for the UserViewSet DRF viewset."""

    ####################################################################
    #
    def test_get_queryset_staff_sees_all(
        self, user_factory: Callable[..., User], make_view: Callable[..., Any]
    ) -> None:
        """
        GIVEN: a staff user and a UserViewSet
        WHEN:  get_queryset() is called
        THEN:  all users are returned
        """
        user_factory()
        user_factory()
        staff = user_factory(is_staff=True)
        view = make_view(UserViewSet, staff, action="list")

        assert view.get_queryset().count() == User.objects.count()

    ####################################################################
    #
    def test_get_queryset_non_staff_sees_only_self(
        self,
        user: User,
        user_factory: Callable[..., User],
        make_view: Callable[..., Any],
    ) -> None:
        """
        GIVEN: a non-staff authenticated user and a UserViewSet
        WHEN:  get_queryset() is called
        THEN:  only the authenticated user appears in the returned queryset
        """
        user_factory()
        view = make_view(UserViewSet, user, action="me")

        assert list(view.get_queryset()) == [user]

    ####################################################################
    #
    def test_me(self, user: User, make_view: Callable[..., Any]) -> None:
        """
        GIVEN: an authenticated user and a UserViewSet
        WHEN:  the me() action is called
        THEN:  the response contains the authenticated user's username,
               name, and absolute API URL
        """
        view = make_view(UserViewSet, user)

        response = view.me(view.request)

        assert response.data == {
            "username": user.username,
            "email": user.email,
            "name": user.name,
            "url": f"http://testserver/api/v1/users/{user.username}/",
            "default_bank_account": None,
            "timezone": "America/Los_Angeles",
            "has_usable_password": True,
        }


########################################################################
########################################################################
#
class TestUserAPIPermissions:
    """Tests that the users API enforces staff-only access."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "is_staff,method,url_suffix,expected_status",
        [
            pytest.param(False, "get", "", 403, id="non-staff-list"),
            pytest.param(False, "get", "{username}/", 403, id="non-staff-get"),
            pytest.param(
                False, "patch", "{username}/", 403, id="non-staff-update"
            ),
            pytest.param(False, "get", "me/", 200, id="non-staff-me"),
            pytest.param(True, "get", "", 200, id="staff-list"),
            pytest.param(True, "get", "{username}/", 200, id="staff-get"),
        ],
    )
    def test_access_by_staff_status(
        self,
        user: User,
        auth_client: APIClient,
        is_staff: bool,
        method: str,
        url_suffix: str,
        expected_status: int,
    ) -> None:
        """
        GIVEN: an authenticated user who is or is not staff
        WHEN:  list, retrieve, update or /me/ is requested
        THEN:  non-staff are denied everything but /me/; staff may list
               and retrieve
        """
        user.is_staff = is_staff
        user.save()
        url = "/api/v1/users/" + url_suffix.format(username=user.username)

        response = getattr(auth_client, method)(url)

        assert response.status_code == expected_status

    ####################################################################
    #
    @pytest.mark.parametrize(
        "method,url",
        [
            pytest.param("get", "/api/v1/users/me/", id="me"),
            pytest.param(
                "post", "/api/v1/users/me/change-password/", id="change-pw"
            ),
        ],
    )
    def test_requires_auth(
        self, api_client: APIClient, method: str, url: str
    ) -> None:
        """
        GIVEN: an unauthenticated client
        WHEN:  a /me/ endpoint is requested
        THEN:  the request is denied with 401
        """
        assert getattr(api_client, method)(url).status_code == 401


# Module-level constants so they can be referenced in @pytest.mark.parametrize
# args, which are evaluated before the class body is complete.
_CURRENT_PW = "OldP@ssword!SufficientlyStr0ng"
_STRONG_PW = "correct-horse-battery-staple-42!"


####################################################################
#
def _change_pw_payload(**overrides: str) -> dict[str, str]:
    """Return a valid change-password payload with `overrides` applied."""
    return {
        "current_password": _CURRENT_PW,
        "new_password": _STRONG_PW,
        "confirm_password": _STRONG_PW,
        **overrides,
    }


########################################################################
########################################################################
#
class TestPasswordChange:
    """Tests for POST /api/v1/users/me/change-password/."""

    URL = "/api/v1/users/me/change-password/"

    ####################################################################
    #
    @pytest.fixture
    def user(self, user_factory: Callable[..., User]) -> User:
        """The default `user`, with a known current password."""
        return user_factory(password=_CURRENT_PW)

    ####################################################################
    #
    def test_change_password_success(
        self,
        user: User,
        auth_client: APIClient,
        mock_send_notification_now: MagicMock,
    ) -> None:
        """
        GIVEN: an authenticated user with a known current password
        WHEN:  a valid change-password POST is submitted
        THEN:  204 is returned, the password is updated, and a notification
               was dispatched
        """
        response = auth_client.post(self.URL, _change_pw_payload())

        user.refresh_from_db()
        check.equal(response.status_code, 204, "succeeds with no body")
        check.is_true(user.check_password(_STRONG_PW), "password updated")
        check.equal(
            len(mock_send_notification_now.delay.call_args_list),
            1,
            "notification dispatched",
        )

    ####################################################################
    #
    def test_ends_other_sessions_keeps_caller_and_api_keys(
        self,
        user: User,
        auth_client: APIClient,
        api_keys_in_every_state: dict[str, APIKey],
        mock_send_notification_now: MagicMock,
    ) -> None:
        """
        GIVEN: a user signed in on two other devices, with an active
               API key
        WHEN:  the password is changed
        THEN:  both other sessions end, the response sets a refresh
               cookie that still works, and the API key stays active
        """
        other_sessions = [RefreshToken.for_user(user) for _ in range(2)]

        response = auth_client.post(self.URL, _change_pw_payload())

        assert response.status_code == 204
        new_cookie = response.cookies[REFRESH_COOKIE_NAME].value
        check.equal(
            [session_valid(s) for s in other_sessions],
            [False, False],
            "other sessions ended",
        )
        check.is_true(session_valid(new_cookie), "caller stays signed in")
        active = api_keys_in_every_state["active"]
        active.refresh_from_db()
        check.is_true(active.is_active, "API key untouched")

    ####################################################################
    #
    @pytest.mark.parametrize(
        "payload_overrides,expected_error_field",
        [
            pytest.param(
                {"current_password": "definitely-wrong"},
                "current_password",
                id="wrong-current-password",
            ),
            pytest.param(
                {"new_password": "password", "confirm_password": "password"},
                "new_password",
                id="weak-password",
            ),
            pytest.param(
                {"confirm_password": _STRONG_PW + "-mismatch"},
                "confirm_password",
                id="passwords-mismatch",
            ),
        ],
    )
    def test_invalid_payload_rejected(
        self,
        auth_client: APIClient,
        payload_overrides: dict[str, str],
        expected_error_field: str,
    ) -> None:
        """
        GIVEN: an authenticated user
        WHEN:  change-password is called with an invalid payload
        THEN:  400 is returned with an error on the relevant field
        """
        response = auth_client.post(
            self.URL, _change_pw_payload(**payload_overrides)
        )

        check.equal(response.status_code, 400, "rejected")
        check.is_in(expected_error_field, response.data, "names the field")

    ####################################################################
    #
    def test_no_usable_password_rejected(
        self, user: User, auth_client: APIClient
    ) -> None:
        """
        GIVEN: a user with no usable password (e.g. invitation flow)
        WHEN:  change-password is called
        THEN:  400 is returned with a 'detail' message
        """
        user.set_unusable_password()
        user.save()

        response = auth_client.post(
            self.URL, _change_pw_payload(current_password="irrelevant")
        )

        check.equal(response.status_code, 400, "rejected")
        check.is_in("detail", response.data, "explains why")
