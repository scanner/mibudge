# system imports
from collections.abc import Callable
from typing import Any

# 3rd party imports
import pytest
from django.conf import LazySettings
from django.test import RequestFactory
from pytest_factoryboy import register

# Project imports
from users.models import User

from .factories import UserInvitationFactory

register(
    UserInvitationFactory
)  # UserInvitationFactory -> user_invitation_factory


####################################################################
#
@pytest.fixture
def site_email_settings(settings: LazySettings) -> None:
    """Pin the site identity that outgoing emails and their links use."""
    settings.SITE_URL = "http://testserver"
    settings.SITE_DISPLAY_NAME = "MiBudge [test]"
    settings.SUPPORT_EMAIL = "support@test.example.com"


####################################################################
#
@pytest.fixture
def make_view(rf: RequestFactory) -> Callable[..., Any]:
    """Return a factory for class-based view instances bound to a user.

    The view gets a GET request from `rf` whose `user` is set, as the
    auth middleware would, so its methods can be called directly.

    Returns:
        A callable `(view_cls, user, **attrs) -> view`; `attrs` are set on
        the view (e.g. `action="list"` for a viewset).
    """

    def _make(view_cls: type, user: User, **attrs: Any) -> Any:
        view = view_cls()
        request = rf.get("/fake-url/")
        request.user = user
        view.request = request
        for name, value in attrs.items():
            setattr(view, name, value)
        return view

    return _make
