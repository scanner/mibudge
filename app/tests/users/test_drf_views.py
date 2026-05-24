"""Tests for the users DRF API views."""

# system imports
#
from collections.abc import Callable

# 3rd party imports
#
import pytest
from django.test import RequestFactory
from pytest_mock import MockerFixture
from rest_framework.test import APIClient

# app imports
#
from users.api.v1.views import UserViewSet
from users.models import User

pytestmark = pytest.mark.django_db


########################################################################
########################################################################
#
class TestUserViewSet:
    """Tests for the UserViewSet DRF viewset."""

    ####################################################################
    #
    def test_get_queryset_staff_sees_all(self, user: User, rf: RequestFactory):
        """
        GIVEN: a staff user and a UserViewSet
        WHEN:  get_queryset() is called
        THEN:  all users are returned
        """
        user.is_staff = True
        user.save()
        view = UserViewSet()
        request = rf.get("/fake-url/")
        request.user = user
        view.request = request
        view.action = "list"

        assert view.get_queryset().count() == User.objects.count()

    ####################################################################
    #
    def test_get_queryset_non_staff_sees_only_self(
        self, user: User, rf: RequestFactory
    ):
        """
        GIVEN: a non-staff authenticated user and a UserViewSet
        WHEN:  get_queryset() is called
        THEN:  only the authenticated user appears in the returned queryset
        """
        view = UserViewSet()
        request = rf.get("/fake-url/")
        request.user = user
        view.request = request
        view.action = "me"

        qs = view.get_queryset()
        assert list(qs) == [user]

    ####################################################################
    #
    def test_me(self, user: User, rf: RequestFactory):
        """
        GIVEN: an authenticated user and a UserViewSet
        WHEN:  the me() action is called
        THEN:  the response contains the authenticated user's username,
               name, and absolute API URL
        """
        view = UserViewSet()
        request = rf.get("/fake-url/")
        request.user = user
        view.request = request

        response = view.me(request)

        assert response.data == {
            "username": user.username,
            "email": user.email,
            "name": user.name,
            "url": f"http://testserver/api/v1/users/{user.username}/",
            "default_bank_account": None,
            "timezone": "America/Los_Angeles",
        }


########################################################################
########################################################################
#
class TestUserAPIPermissions:
    """Tests that the users API enforces staff-only access."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "method,url_suffix",
        [
            pytest.param("get", "", id="list"),
            pytest.param("get", "{username}/", id="retrieve"),
            pytest.param("patch", "{username}/", id="update"),
        ],
    )
    def test_non_staff_denied(self, user: User, method: str, url_suffix: str):
        """
        GIVEN: a non-staff authenticated user
        WHEN:  list, retrieve, or update is attempted on the users API
        THEN:  the request is denied with 403
        """
        client = APIClient()
        client.force_authenticate(user=user)
        url = "/api/v1/users/" + url_suffix.format(username=user.username)
        response = getattr(client, method)(url)
        assert response.status_code == 403

    ####################################################################
    #
    @pytest.mark.parametrize(
        "method,url_suffix",
        [
            pytest.param("get", "", id="list"),
            pytest.param("get", "{username}/", id="retrieve"),
        ],
    )
    def test_staff_allowed(self, user: User, method: str, url_suffix: str):
        """
        GIVEN: a staff user
        WHEN:  list or retrieve is attempted on the users API
        THEN:  the request succeeds with 200
        """
        user.is_staff = True
        user.save()
        client = APIClient()
        client.force_authenticate(user=user)
        url = "/api/v1/users/" + url_suffix.format(username=user.username)
        response = getattr(client, method)(url)
        assert response.status_code == 200

    ####################################################################
    #
    def test_me_available_to_non_staff(self, user: User):
        """
        GIVEN: a non-staff authenticated user
        WHEN:  the /api/users/me/ endpoint is accessed
        THEN:  the request succeeds with 200
        """
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get("/api/v1/users/me/")
        assert response.status_code == 200
        assert response.data["username"] == user.username

    ####################################################################
    #
    def test_me_requires_auth(self):
        """
        GIVEN: an unauthenticated client
        WHEN:  the /api/users/me/ endpoint is accessed
        THEN:  the request is denied with 401
        """
        client = APIClient()
        response = client.get("/api/v1/users/me/")
        assert response.status_code == 401


# Module-level constants so they can be referenced in @pytest.mark.parametrize
# args, which are evaluated before the class body is complete.
_CURRENT_PW = "OldP@ssword!SufficientlyStr0ng"
_STRONG_PW = "correct-horse-battery-staple-42!"


########################################################################
########################################################################
#
class TestPasswordChange:
    """Tests for POST /api/v1/users/me/change-password/."""

    URL = "/api/v1/users/me/change-password/"

    ####################################################################
    #
    def test_change_password_success(
        self, user_factory: Callable[..., User], mocker: MockerFixture
    ) -> None:
        """
        GIVEN: an authenticated user with a known current password
        WHEN:  a valid change-password POST is submitted
        THEN:  204 is returned, the password is updated, and a notification
               was dispatched
        """
        mock_send = mocker.patch("notifications.tasks.send_notification_now")
        user = user_factory(password=_CURRENT_PW)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            self.URL,
            {
                "current_password": _CURRENT_PW,
                "new_password": _STRONG_PW,
                "confirm_password": _STRONG_PW,
            },
        )

        assert response.status_code == 204
        user.refresh_from_db()
        assert user.check_password(_STRONG_PW)
        mock_send.delay.assert_called_once()

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
        user_factory: Callable[..., User],
        payload_overrides: dict,
        expected_error_field: str,
    ) -> None:
        """
        GIVEN: an authenticated user
        WHEN:  change-password is called with an invalid payload
        THEN:  400 is returned with an error on the relevant field
        """
        user = user_factory(password=_CURRENT_PW)
        client = APIClient()
        client.force_authenticate(user=user)

        payload = {
            "current_password": _CURRENT_PW,
            "new_password": _STRONG_PW,
            "confirm_password": _STRONG_PW,
            **payload_overrides,
        }
        response = client.post(self.URL, payload)

        assert response.status_code == 400
        assert expected_error_field in response.data

    ####################################################################
    #
    def test_no_usable_password_rejected(
        self, user_factory: Callable[..., User]
    ) -> None:
        """
        GIVEN: a user with no usable password (e.g. invitation flow)
        WHEN:  change-password is called
        THEN:  400 is returned with a 'detail' message
        """
        user = user_factory()
        user.set_unusable_password()
        user.save()
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            self.URL,
            {
                "current_password": "irrelevant",
                "new_password": _STRONG_PW,
                "confirm_password": _STRONG_PW,
            },
        )

        assert response.status_code == 400
        assert "detail" in response.data

    ####################################################################
    #
    def test_requires_auth(self) -> None:
        """
        GIVEN: an unauthenticated client
        WHEN:  change-password is called
        THEN:  401 is returned
        """
        client = APIClient()
        response = client.post(self.URL, {})
        assert response.status_code == 401
