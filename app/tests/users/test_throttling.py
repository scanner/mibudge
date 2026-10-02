#!/usr/bin/env python
#
"""Test the rate limits on login, token refresh and password change."""

# system imports
from collections.abc import Callable, Iterator

# 3rd party imports
import pytest
import pytest_check as check
from django.urls import reverse
from faker import Faker
from pytest_mock import MockerFixture
from rest_framework.response import Response
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle

# Project imports
from users.models import User
from users.throttling import LOGIN_DEVICE_COOKIE_NAME

pytestmark = pytest.mark.django_db

PASSWORD = "a-known-passphrase-for-throttle-tests-17!"
LOGIN_URL = reverse("token-obtain")


####################################################################
#
@pytest.fixture
def user(user_factory: Callable[..., User]) -> User:
    """The default `user`, with a known password."""
    return user_factory(password=PASSWORD)


####################################################################
#
@pytest.fixture
def set_throttle_rates(
    mocker: MockerFixture,
) -> Iterator[Callable[..., None]]:
    """Return a callable that sets throttle rates for this test.

    The defaults are small, so a test reaches each limit in a few
    requests; the anonymous limit is high enough to stay out of the way
    unless a test lowers it.
    """
    rates = {
        "anon": "1000/hour",
        "user": "1000/hour",
        "login": "3/min",
        "login_email": "2/hour",
        "login_device": "2/hour",
        "password_change": "2/hour",
        "token_refresh": "2/min",
    }
    # `THROTTLE_RATES` is bound when DRF's settings are first read, so
    # the rates are patched on the class every throttle inherits from.
    #
    mocker.patch.object(SimpleRateThrottle, "THROTTLE_RATES", rates)

    def _set(**overrides: str) -> None:
        rates.update(overrides)

    yield _set


####################################################################
#
@pytest.fixture
def throttle_rates(set_throttle_rates: Callable[..., None]) -> None:
    """The small default rates from `set_throttle_rates`."""


####################################################################
#
@pytest.fixture
def login(api_client: APIClient) -> Callable[..., Response]:
    """Return a callable that posts a login from a given client address."""

    def _login(
        email: str, password: str, addr: str = "198.51.100.1"
    ) -> Response:
        return api_client.post(
            LOGIN_URL,
            {"email": email, "password": password},
            format="json",
            REMOTE_ADDR=addr,
        )

    return _login


####################################################################
#
@pytest.fixture
def device_cookie(
    request: pytest.FixtureRequest,
    user: User,
    user_factory: Callable[..., User],
    login: Callable[..., Response],
    api_client: APIClient,
) -> str:
    """A device cookie in `api_client`, as left by an earlier login.

    `user` signs in once from this client, which sets the cookie.
    Indirect-parametrize with:
      - 'valid': the cookie as issued.
      - 'tampered': the cookie's signature altered.
      - 'other-user': a cookie issued to a different user.
      - 'stale-password': `user` has changed password since.

    Returns:
        The variant name.
    """
    variant = getattr(request, "param", "valid")
    if variant == "other-user":
        other = user_factory(password=PASSWORD)
        assert login(other.email, PASSWORD).status_code == 200
    else:
        assert login(user.email, PASSWORD).status_code == 200
    cookie = api_client.cookies[LOGIN_DEVICE_COOKIE_NAME]
    if variant == "tampered":
        tampered = "x" + cookie.value
        cookie.set(cookie.key, tampered, tampered)
    if variant == "stale-password":
        user.set_password(PASSWORD)
        user.save()
    return variant


####################################################################
#
@pytest.fixture
def exhaust_email_limit(
    api_client: APIClient, login: Callable[..., Response]
) -> Callable[[str], None]:
    """Return a callable that uses up an email's per-email login limit.

    The attempts come from fresh addresses and a browser without this
    client's device cookie, as an attacker's would.
    """

    def _exhaust(email: str) -> None:
        saved = api_client.cookies.pop(LOGIN_DEVICE_COOKIE_NAME, None)
        for n in range(10):
            if login(email, "wrong", addr=f"203.0.113.{n}").status_code == 429:
                break
        else:
            raise AssertionError("per-email limit never reached")
        if saved is not None:
            api_client.cookies[LOGIN_DEVICE_COOKIE_NAME] = saved

    return _exhaust


########################################################################
########################################################################
#
@pytest.mark.usefixtures("throttle_rates")
class TestLoginThrottles:
    """Login is limited per client address and per email."""

    ####################################################################
    #
    def test_per_address_limit(
        self, login: Callable[..., Response], faker: Faker
    ) -> None:
        """
        GIVEN: a client address that has made the allowed login attempts
        WHEN:  it attempts again, against yet another email
        THEN:  it is refused with 429, a `Retry-After`, and a message
               saying there were too many sign-in attempts
        """
        statuses = [
            login(faker.unique.email(), "wrong").status_code for _ in range(3)
        ]
        refused = login(faker.unique.email(), "wrong")

        check.equal(statuses, [401, 401, 401], "allowed attempts")
        check.equal(refused.status_code, 429, "refused")
        check.is_in("Retry-After", refused.headers, "says when to retry")
        check.is_true(
            refused.json()["detail"].startswith("Too many sign-in attempts."),
            "worded for the sign-in form",
        )

    ####################################################################
    #
    def test_per_email_limit_spans_addresses(
        self, login: Callable[..., Response], user: User, faker: Faker
    ) -> None:
        """
        GIVEN: login attempts against one email from many addresses
        WHEN:  the per-email limit is used up
        THEN:  further attempts against it are refused, even with the
               right password, while another email is unaffected
        """
        attempts = [
            login(user.email, "wrong", addr=f"203.0.113.{n}").status_code
            for n in range(2)
        ]
        owner = login(user.email, PASSWORD, addr="192.0.2.50")
        other = login(faker.unique.email(), "wrong", addr="192.0.2.51")

        check.equal(attempts, [401, 401], "allowed attempts")
        check.equal(owner.status_code, 429, "email refused")
        check.equal(other.status_code, 401, "other email unaffected")

    ####################################################################
    #
    @pytest.mark.parametrize(
        "device_cookie,status",
        [
            ("valid", 200),
            ("tampered", 429),
            ("other-user", 429),
            ("stale-password", 429),
        ],
        indirect=["device_cookie"],
    )
    def test_known_browser_bypasses_email_limit(
        self,
        user: User,
        device_cookie: str,
        exhaust_email_limit: Callable[[str], None],
        login: Callable[..., Response],
        status: int,
    ) -> None:
        """
        GIVEN: a browser holding a device cookie, and an email whose
               per-email limit others have used up
        WHEN:  the owner signs in from that browser
        THEN:  they get in when the cookie is one we issued to them
               under their current password; otherwise the per-email
               limit refuses them
        """
        exhaust_email_limit(user.email)

        response = login(user.email, PASSWORD, addr="192.0.2.50")

        assert response.status_code == status

    ####################################################################
    #
    def test_known_browser_has_its_own_limit(
        self,
        user: User,
        device_cookie: str,
        login: Callable[..., Response],
    ) -> None:
        """
        GIVEN: a browser holding a valid device cookie
        WHEN:  it uses up the per-device limit with wrong passwords
        THEN:  its next attempt is refused, even with the right password
        """
        attempts = [
            login(user.email, "wrong", addr="192.0.2.50").status_code
            for _ in range(2)
        ]
        refused = login(user.email, PASSWORD, addr="192.0.2.50")

        check.equal(attempts, [401, 401], "allowed attempts")
        check.equal(refused.status_code, 429, "refused")


########################################################################
########################################################################
#
class TestOtherCredentialThrottles:
    """Password change is limited per user, refresh per address."""

    ####################################################################
    #
    @pytest.mark.usefixtures("throttle_rates")
    def test_password_change_limit(self, auth_client: APIClient) -> None:
        """
        GIVEN: a user who has made the allowed password-change attempts
        WHEN:  they attempt again
        THEN:  it is refused with 429
        """
        url = reverse("api_v1:user-change-password")
        payload = {
            "current_password": "wrong",
            "new_password": "correct-horse-battery-staple-42!",
            "confirm_password": "correct-horse-battery-staple-42!",
        }

        statuses = [
            auth_client.post(url, payload, format="json").status_code
            for _ in range(3)
        ]

        assert statuses == [400, 400, 429]

    ####################################################################
    #
    def test_refresh_limit_replaces_anon(
        self, set_throttle_rates: Callable[..., None], api_client: APIClient
    ) -> None:
        """
        GIVEN: an anonymous limit lower than the refresh limit
        WHEN:  a client address refreshes repeatedly
        THEN:  the refresh limit alone applies: refreshes go through up
               to it, and the next is refused with 429
        """
        set_throttle_rates(anon="1/hour")
        url = reverse("token-refresh")

        statuses = [api_client.post(url).status_code for _ in range(3)]

        assert statuses == [401, 401, 429]
