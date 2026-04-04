"""Tests for users views."""

# system imports
#

# 3rd party imports
#
import pytest
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory
from django.urls import reverse

# app imports
#
from tests.users.factories import UserFactory
from users.forms import UserChangeForm
from users.models import User
from users.views import (
    UserRedirectView,
    UserUpdateView,
    user_detail_view,
)

pytestmark = pytest.mark.django_db


########################################################################
########################################################################
#
class TestUserUpdateView:
    """Tests for UserUpdateView -- update the authenticated user's profile."""

    def dummy_get_response(self, request: HttpRequest) -> HttpResponse:
        return HttpResponse()

    def test_get_success_url(self, user: User, rf: RequestFactory):
        """
        GIVEN: an authenticated user and a UserUpdateView
        WHEN:  get_success_url() is called
        THEN:  the URL resolves to the user's detail page
        """
        view = UserUpdateView()
        request = rf.get("/fake-url/")
        request.user = user
        view.request = request

        assert view.get_success_url() == f"/users/{user.username}/"

    def test_get_object(self, user: User, rf: RequestFactory):
        """
        GIVEN: an authenticated user and a UserUpdateView
        WHEN:  get_object() is called
        THEN:  the view returns the authenticated user, not a queryset lookup
        """
        view = UserUpdateView()
        request = rf.get("/fake-url/")
        request.user = user
        view.request = request

        assert view.get_object() == user

    def test_form_valid(self, user: User, rf: RequestFactory):
        """
        GIVEN: an authenticated user submitting a valid profile update
        WHEN:  form_valid() is called
        THEN:  a success flash message is added to the request
        """
        view = UserUpdateView()
        request = rf.get("/fake-url/")
        SessionMiddleware(self.dummy_get_response).process_request(request)
        MessageMiddleware(self.dummy_get_response).process_request(request)
        request.user = user
        view.request = request

        form = UserChangeForm()
        form.cleaned_data = {}
        view.form_valid(form)

        messages_sent = [m.message for m in messages.get_messages(request)]
        assert messages_sent == ["Information successfully updated"]


########################################################################
########################################################################
#
class TestUserRedirectView:
    """Tests for UserRedirectView -- redirects the user to their detail page."""

    def test_get_redirect_url(self, user: User, rf: RequestFactory):
        """
        GIVEN: an authenticated user and a UserRedirectView
        WHEN:  get_redirect_url() is called
        THEN:  the URL resolves to the user's detail page
        """
        view = UserRedirectView()
        request = rf.get("/fake-url")
        request.user = user
        view.request = request

        assert view.get_redirect_url() == f"/users/{user.username}/"


########################################################################
########################################################################
#
class TestUserDetailView:
    """Tests for the user_detail_view -- displays a user's public profile."""

    def test_authenticated(self, user: User, rf: RequestFactory):
        """
        GIVEN: an authenticated user requesting another user's detail page
        WHEN:  the view is called
        THEN:  a 200 response is returned
        """
        request = rf.get("/fake-url/")
        # factory-boy stubs don't express that UserFactory() returns a User instance -- revisit if factory-boy stubs improve
        request.user = UserFactory()  # type: ignore[assignment]

        response = user_detail_view(request, username=user.username)

        assert response.status_code == 200

    def test_not_authenticated(self, user: User, rf: RequestFactory):
        """
        GIVEN: an anonymous (unauthenticated) user requesting a detail page
        WHEN:  the view is called
        THEN:  the user is redirected to the login page with a next parameter
        """
        request = rf.get("/fake-url/")
        request.user = AnonymousUser()

        response = user_detail_view(request, username=user.username)
        login_url = reverse(settings.LOGIN_URL)

        assert response.status_code == 302
        # user_detail_view returns HttpResponseRedirect which has .url, but the
        # type is declared as HttpResponseBase which doesn't -- revisit if django-stubs improve
        assert response.url == f"{login_url}?next=/fake-url/"  # type: ignore[attr-defined]
