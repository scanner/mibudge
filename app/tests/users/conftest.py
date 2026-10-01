# system imports
from collections.abc import Callable
from datetime import timedelta
from typing import Any

# 3rd party imports
import pytest
from django.test import RequestFactory
from django.utils import timezone
from pytest_factoryboy import register

# Project imports
from users.models import APIKey, User

from .factories import UserInvitationFactory

register(
    UserInvitationFactory
)  # UserInvitationFactory -> user_invitation_factory


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


####################################################################
#
@pytest.fixture
def api_keys_in_every_state(user: User) -> dict[str, APIKey]:
    """API keys for `user`: one active, one revoked, one expired.

    Only the active key counts as live -- it is the one a password
    reset lists and revoke-all revokes.
    """
    active, _ = APIKey.make(user, "active importer")
    revoked, _ = APIKey.make(user, "revoked importer")
    revoked.revoke()
    expired, _ = APIKey.make(
        user, "expired importer", expires_at=timezone.now() - timedelta(days=1)
    )
    return {"active": active, "revoked": revoked, "expired": expired}


####################################################################
#
@pytest.fixture
def active_keys(request: pytest.FixtureRequest, user: User) -> list[APIKey]:
    """`request.param` active API keys for `user`."""
    return [APIKey.make(user, f"importer {n}")[0] for n in range(request.param)]
