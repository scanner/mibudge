# system imports
#
import os
import types
from collections.abc import Callable, Generator
from unittest.mock import MagicMock

# 3rd party imports
import py
import pytest
import redis
from django.conf import LazySettings
from django.db import connections
from fakeredis import FakeConnection, FakeServer
from pytest_factoryboy import register
from pytest_mock import MockerFixture
from rest_framework.test import APIClient

# project imports
import notifications.service as notifications_service
from common.db import SQLITE_ENGINE, apply_sqlite_locking
from tests.users.factories import UserFactory
from users.models import APIKey, User

register(UserFactory)  # UserFactory -> user_factory fixture


# When set, tests run against this Postgres database instead of the
# in-memory SQLite default.  pytest-django creates and destroys a
# `test_<name>` database next to it, so the role needs CREATEDB.
#
POSTGRES_TEST_URL_ENV = "MIBUDGE_TEST_DATABASE_URL"


####################################################################
#
def postgres_test_mode() -> bool:
    """Return True when the opt-in Postgres test mode is active."""
    return bool(os.environ.get(POSTGRES_TEST_URL_ENV))


####################################################################
#
def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip `postgres`-marked tests unless the Postgres mode is active.

    Args:
        config: The pytest config (unused).
        items: The collected test items, modified in place.
    """
    if postgres_test_mode():
        return
    skip = pytest.mark.skip(
        reason=f"needs Postgres; set {POSTGRES_TEST_URL_ENV} to run"
    )
    for item in items:
        if "postgres" in item.keywords:
            item.add_marker(skip)


####################################################################
#
@pytest.fixture(scope="session")
def django_db_modify_db_settings(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """
    Point the test database at a SQLite file, or at Postgres when
    `MIBUDGE_TEST_DATABASE_URL` is set.

    The SQLite test database is a file, not `:memory:`, so threads in
    the concurrency tests get their own connections with SQLite's
    file-level write locking.  Django's in-memory test database uses a
    shared cache, whose table-level locks fail at once instead of
    waiting.  The file is opened with the same `BEGIN IMMEDIATE`
    transaction mode as production SQLite (`common.db`).

    pytest-django calls this session-scoped fixture inside
    ``django_db_setup``, just before ``setup_databases()`` runs, making it
    the correct place to swap the backend regardless of what ``DATABASE_URL``
    is set to in the environment or ``.env`` file.

    Returns:
        None
    """
    import environ
    from django.conf import settings

    db = settings.DATABASES["default"]
    if postgres_test_mode():
        # Overwrite only the keys the URL defines; Django has already
        # filled in its defaults (AUTOCOMMIT, TEST, ...) on this dict.
        #
        url = os.environ[POSTGRES_TEST_URL_ENV]
        db.update(environ.Env.db_url_config(url))
    else:
        db["ENGINE"] = SQLITE_ENGINE
        db["NAME"] = ":memory:"
        db.setdefault("TEST", {})["NAME"] = str(
            tmp_path_factory.mktemp("db") / "test_mibudge.sqlite3"
        )
        apply_sqlite_locking(db)

    # Discard the cached DatabaseWrapper -- it was built from the
    # original settings. Deleting it forces the next access to construct
    # a fresh wrapper from the updated dict.
    try:
        del connections["default"]
    except Exception:
        pass


####################################################################
#
@pytest.fixture(autouse=True)
def use_fakeredis(
    settings: LazySettings,
    mocker: MockerFixture,
) -> Generator[redis.StrictRedis]:
    """
    Set up a FakeServer and redirect all Redis access to it for the
    duration of each test. App code must use utils.redis_client() so
    the monkeypatched pool is picked up automatically.

    Args:
        settings: The pytest-django ``settings`` fixture for overriding
            Django settings within the test.
        mocker: The pytest-mock ``mocker`` fixture used to replace
            ``common.redis.REDIS_CONNECTION_POOL`` with a fake pool.

    Yields:
        A ``redis.StrictRedis`` client connected to the FakeServer, for
        tests that need direct access to the fake Redis instance.
    """
    server = FakeServer()
    fake_pool = redis.ConnectionPool(
        server=server, connection_class=FakeConnection
    )
    mocker.patch("common.redis.REDIS_CONNECTION_POOL", fake_pool)

    # django-redis is the cache backend in non-DEBUG mode; replace it with
    # an in-memory cache so tests never need a real Redis server.
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }

    yield redis.StrictRedis(connection_pool=fake_pool)


####################################################################
#
@pytest.fixture(autouse=True)
def media_storage(settings: LazySettings, tmpdir: py.path.local) -> None:
    """
    Redirect Django's MEDIA_ROOT to a temporary directory.

    Args:
        settings: The pytest-django ``settings`` fixture for overriding
            Django settings within the test.
        tmpdir: The pytest ``tmpdir`` fixture providing a temporary
            directory unique to each test invocation.

    Returns:
        None
    """
    settings.MEDIA_ROOT = tmpdir.strpath


####################################################################
#
@pytest.fixture(autouse=True)
def disable_ssl_redirect(settings: LazySettings) -> None:
    """
    Disable HTTPS redirects so the test client can use plain HTTP.

    SECURE_SSL_REDIRECT is True in production settings; without this
    override every request would receive a 301 redirect and tests
    would fail.

    Args:
        settings: The pytest-django ``settings`` fixture for overriding
            Django settings within the test.

    Returns:
        None
    """
    settings.SECURE_SSL_REDIRECT = False


####################################################################
#
@pytest.fixture
def mock_send_notification_now(mocker: MockerFixture) -> MagicMock:
    """Patch send_notification_now to prevent Celery broker connections in tests.

    Use this fixture in any test that triggers a CRITICAL notification.
    Without it, notify() calls send_notification_now.delay() which tries to
    connect to the real Celery broker and fails in the test environment.

    notify() dispatches via db_transaction.on_commit() so that the task is
    enqueued only after the surrounding request transaction commits
    (ATOMIC_REQUESTS=True).  In tests the outer transaction never commits, so
    we also patch notifications.service.db_transaction locally (not globally)
    to fire on_commit callbacks immediately.  Other modules' on_commit calls
    (e.g. attempt_link_transaction in moneypools) are not affected.

    Returns:
        The MagicMock replacing send_notification_now, so callers can assert
        .delay() was called with the expected notification ID.
    """
    mock_tx = types.SimpleNamespace(on_commit=lambda fn: fn())
    mocker.patch.object(notifications_service, "db_transaction", mock_tx)
    return mocker.patch("notifications.tasks.send_notification_now")


####################################################################
#
@pytest.fixture
def user() -> User:
    """
    Return a persisted User instance created by UserFactory.

    Returns:
        A saved ``User`` model instance.
    """
    # factory-boy stubs don't express that UserFactory() returns a User
    # instance -- revisit if factory-boy stubs improve
    return UserFactory()  # type: ignore[return-value]


####################################################################
#
@pytest.fixture
def api_client() -> APIClient:
    """An unauthenticated DRF test client."""
    return APIClient()


####################################################################
#
@pytest.fixture
def auth_client(user: User) -> APIClient:
    """A DRF test client authenticated as the default `user` fixture."""
    client = APIClient()
    client.force_authenticate(user=user)
    return client


####################################################################
#
@pytest.fixture
def make_api_key_client() -> Callable[..., APIClient]:
    """Return a factory for clients that authenticate with an API key.

    Each call mints a new `APIKey` for the given user and returns a
    client sending it as `Authorization: Api-Key <plaintext>`, the
    same path the importers and 3rd-party services take.

    Returns:
        A callable `(user, name="test key") -> APIClient`.
    """

    def _make(user: User, name: str = "test key") -> APIClient:
        _, plaintext = APIKey.make(user, name)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Api-Key {plaintext}")
        return client

    return _make


####################################################################
#
@pytest.fixture(params=["jwt", "api_key"])
def any_auth_client(
    request: pytest.FixtureRequest,
    user: User,
    make_api_key_client: Callable[..., APIClient],
) -> APIClient:
    """A client for the default `user`, once per authentication method.

    Tests that use this fixture run twice: once with an interactive
    (force-authenticated, as for a JWT session) client and once with an
    API-key client.  Use it for endpoints that machine credentials may
    reach, to show both paths behave the same.

    Args:
        request: The pytest request; `request.param` names the method.
        user: The default `user` fixture the client acts as.
        make_api_key_client: Factory for API-key clients.

    Returns:
        An `APIClient` authenticated as `user`.
    """
    # Built directly from `user` rather than from `auth_client`, so a
    # module that overrides `auth_client` with another user still gets
    # the same user on both parametrizations.
    #
    if request.param == "api_key":
        return make_api_key_client(user)
    client = APIClient()
    client.force_authenticate(user=user)
    return client
