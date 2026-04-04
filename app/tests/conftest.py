# system imports
#
from collections.abc import Generator

# 3rd party imports
import py
import pytest
import redis

# project imports
import utils
from django.conf import LazySettings, settings
from django.db import connections
from fakeredis import FakeConnection, FakeServer
from pytest_factoryboy import register

from tests.users.factories import UserFactory
from users.models import User


####################################################################
#
@pytest.fixture(scope="session")
def django_db_modify_db_settings() -> None:
    """
    Override the database configuration to use in-memory SQLite so tests
    always use SQLite for their database.

    pytest-django calls this session-scoped fixture inside
    ``django_db_setup``, just before ``setup_databases()`` runs, making it
    the correct place to swap the backend regardless of what ``DATABASE_URL``
    is set to in the environment or ``.env`` file.

    Returns:
        None
    """
    db = settings.DATABASES["default"]
    db["ENGINE"] = "django.db.backends.sqlite3"
    db["NAME"] = ":memory:"

    # Discard the cached DatabaseWrapper -- it is still a PostgreSQL class
    # instance even after the settings change above. Deleting it forces the
    # next access to construct a fresh SQLite wrapper from the updated dict.
    try:
        del connections["default"]
    except Exception:
        pass


####################################################################
#
@pytest.fixture(autouse=True)
def use_fakeredis(
    settings: LazySettings, monkeypatch: pytest.MonkeyPatch
) -> Generator[redis.StrictRedis]:
    """
    Set up a FakeServer and redirect all Redis access to it for the
    duration of each test. App code must use utils.redis_client() so
    the monkeypatched pool is picked up automatically.

    Args:
        settings: The pytest-django ``settings`` fixture for overriding
            Django settings within the test.
        monkeypatch: The pytest ``monkeypatch`` fixture used to replace
            ``utils.REDIS_CONNECTION_POOL`` with a fake pool.

    Yields:
        A ``redis.StrictRedis`` client connected to the FakeServer, for
        tests that need direct access to the fake Redis instance.
    """
    server = FakeServer()
    fake_pool = redis.ConnectionPool(
        server=server, connection_class=FakeConnection
    )
    monkeypatch.setattr(utils, "REDIS_CONNECTION_POOL", fake_pool)

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
def user() -> User:
    """
    Return a persisted User instance created by UserFactory.

    Returns:
        A saved ``User`` model instance.
    """
    # factory-boy stubs don't express that UserFactory() returns a User
    # instance -- revisit if factory-boy stubs improve
    return UserFactory()  # type: ignore[return-value]


register(UserFactory)
