"""Tests for the users DRF API views."""

# system imports
#

# 3rd party imports
#
import pytest
from django.test import RequestFactory

# app imports
#
from users.api.views import UserViewSet
from users.models import User

pytestmark = pytest.mark.django_db


########################################################################
########################################################################
#
class TestUserViewSet:
    """Tests for the UserViewSet DRF viewset."""

    def test_get_queryset(self, user: User, rf: RequestFactory):
        """
        GIVEN: an authenticated user and a UserViewSet
        WHEN:  get_queryset() is called
        THEN:  the authenticated user appears in the returned queryset
        """
        view = UserViewSet()
        request = rf.get("/fake-url/")
        request.user = user
        view.request = request

        assert user in view.get_queryset()

    def test_me(self, user: User, rf: RequestFactory):
        """
        GIVEN: an authenticated user and a UserViewSet
        WHEN:  the me() action is called
        THEN:  the response contains the authenticated user's username, name,
               and absolute API URL
        """
        view = UserViewSet()
        request = rf.get("/fake-url/")
        request.user = user
        view.request = request

        response = view.me(request)

        assert response.data == {
            "username": user.username,
            "name": user.name,
            "url": f"http://testserver/api/users/{user.username}/",
        }
