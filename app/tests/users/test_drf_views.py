"""Tests for the users DRF API views."""

# 3rd party imports
#
import pytest
from django.test import RequestFactory
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
            "name": user.name,
            "url": f"http://testserver/api/v1/users/{user.username}/",
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
