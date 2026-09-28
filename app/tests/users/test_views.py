"""Tests for users views."""

# system imports
#
from collections.abc import Callable
from typing import Any

# 3rd party imports
#
import pytest
import pytest_check as check
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory
from pytest_mock import MockerFixture

# app imports
#
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

    def test_get_object(
        self, user: User, make_view: Callable[..., Any]
    ) -> None:
        """
        GIVEN: an authenticated user and a UserUpdateView
        WHEN:  get_object() is called
        THEN:  the view returns the authenticated user, not a queryset lookup
        """
        assert make_view(UserUpdateView, user).get_object() == user

    def test_form_valid(
        self, user: User, make_view: Callable[..., Any], mocker: MockerFixture
    ) -> None:
        """
        GIVEN: an authenticated user submitting a valid profile update
        WHEN:  form_valid() is called
        THEN:  a success flash message is added to the request
        """
        view = make_view(UserUpdateView, user)
        SessionMiddleware(self.dummy_get_response).process_request(view.request)
        MessageMiddleware(self.dummy_get_response).process_request(view.request)

        form = UserChangeForm()
        form.cleaned_data = {}
        # Stub out form.save() -- this test is only checking the flash message,
        # not the DB write.  Without the stub, saving an empty UserChangeForm
        # (with blank email) collides with the unique-email constraint.
        mocker.patch.object(form, "save", return_value=user)
        view.form_valid(form)

        messages_sent = [m.message for m in messages.get_messages(view.request)]
        assert messages_sent == ["Information successfully updated"]


########################################################################
########################################################################
#
@pytest.mark.parametrize(
    "view_cls,method",
    [
        pytest.param(UserUpdateView, "get_success_url", id="update-success"),
        pytest.param(UserRedirectView, "get_redirect_url", id="redirect"),
    ],
)
def test_view_sends_user_to_own_detail_page(
    user: User, make_view: Callable[..., Any], view_cls: type, method: str
) -> None:
    """
    GIVEN: an authenticated user and a view that redirects on completion
    WHEN:  the view computes its redirect target
    THEN:  the target is the user's own detail page
    """
    view = make_view(view_cls, user)

    assert getattr(view, method)() == f"/users/{user.username}/"


########################################################################
########################################################################
#
class TestUserDetailView:
    """Tests for the user_detail_view -- displays a user's public profile."""

    def test_authenticated(
        self,
        user: User,
        user_factory: Callable[..., User],
        rf: RequestFactory,
    ) -> None:
        """
        GIVEN: an authenticated user requesting another user's detail page
        WHEN:  the view is called
        THEN:  a 200 response is returned
        """
        request = rf.get("/fake-url/")
        request.user = user_factory()

        response = user_detail_view(request, username=user.username)

        assert response.status_code == 200

    def test_not_authenticated(self, user: User, rf: RequestFactory) -> None:
        """
        GIVEN: an anonymous (unauthenticated) user requesting a detail page
        WHEN:  the view is called
        THEN:  the user is redirected to the login page with a next parameter
        """
        request = rf.get("/fake-url/")
        request.user = AnonymousUser()

        response = user_detail_view(request, username=user.username)

        check.equal(response.status_code, 302, "redirected")
        # LOGIN_URL is a path ("/app/login/"), not a URL name, so no reverse().
        # user_detail_view returns HttpResponseRedirect which has .url, but the
        # type is declared as HttpResponseBase which doesn't -- revisit if django-stubs improve
        check.equal(
            response.url,  # type: ignore[attr-defined]
            f"{settings.LOGIN_URL}?next=/fake-url/",
            "to the login page, returning here after",
        )
