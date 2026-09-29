"""Tests for JWT-related auth views: token obtain, refresh, logout, SpaShellView."""

# system imports
#
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

# 3rd party imports
#
import pytest
import pytest_check as check
from django.conf import LazySettings
from django.test import Client
from django.urls import reverse
from django_vite.core.asset_loader import DjangoViteAssetLoader
from faker import Faker
from freezegun import freeze_time
from rest_framework_simplejwt.tokens import RefreshToken, UntypedToken

# app imports
#
from users.models import User
from users.views import REFRESH_COOKIE_NAME

if TYPE_CHECKING:
    # django-stubs' name for what the test client returns.
    from django.test.client import _MonkeyPatchedWSGIResponse as Response

pytestmark = pytest.mark.django_db


####################################################################
#
@pytest.fixture
def vite_dev_mode(settings: LazySettings) -> None:
    """
    Override DJANGO_VITE to use dev mode so the spa/shell.html template
    renders without a Vite build manifest on disk.

    django-vite uses a singleton (DjangoViteAssetLoader._instance) that is
    populated at startup. Resetting it forces re-initialization from the
    patched settings on the next template render.

    Args:
        settings: The pytest-django ``settings`` fixture.

    Returns:
        None
    """
    settings.DJANGO_VITE = {"default": {"dev_mode": True}}
    # Reset the singleton so it re-reads the patched settings on next use.
    DjangoViteAssetLoader._instance = None


####################################################################
#
@pytest.fixture
def login_response(
    client: Client, user_factory: Callable[..., User], faker: Faker
) -> tuple[User, "Response"]:
    """Log a fresh user in through POST /api/token/.

    Returns:
        The user and the login response.
    """
    password = faker.password(length=20)
    user = user_factory(password=password)
    response = client.post(
        reverse("token-obtain"),
        data={"email": user.email, "password": password},
        content_type="application/json",
    )
    return user, response


########################################################################
########################################################################
#
class TestCookieTokenObtainPairView:
    """Tests for CookieTokenObtainPairView -- SPA login endpoint."""

    ####################################################################
    #
    def test_invalid_credentials_returns_401(
        self, client: Client, faker: Faker
    ) -> None:
        """
        GIVEN: a request with invalid credentials
        WHEN:  POST /api/token/
        THEN:  the response status is 401 and no refresh cookie is set
        """
        response = client.post(
            reverse("token-obtain"),
            data={"email": faker.email(), "password": faker.password()},
            content_type="application/json",
        )

        check.equal(response.status_code, 401, "refused")
        check.is_not_in(
            REFRESH_COOKIE_NAME, response.cookies, "no refresh cookie"
        )

    ####################################################################
    #
    def test_valid_credentials_set_httponly_refresh_cookie(
        self,
        login_response: tuple[User, "Response"],
        settings: LazySettings,
    ) -> None:
        """
        GIVEN: valid credentials
        WHEN:  POST /api/token/
        THEN:  the body carries an access token for the user, but no
               refresh token; the refresh token is set as an httpOnly
               cookie whose max-age matches SIMPLE_JWT
               REFRESH_TOKEN_LIFETIME
        """
        user, response = login_response
        lifetime = cast(
            timedelta, settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"]
        )

        assert response.status_code == 200
        body = response.json()
        check.is_not_in("refresh", body, "no refresh token in the body")
        check.equal(
            int(UntypedToken(body["access"])["user_id"]),
            user.pk,
            "access token is a valid JWT for the user",
        )
        assert REFRESH_COOKIE_NAME in response.cookies
        cookie = response.cookies[REFRESH_COOKIE_NAME]
        check.is_true(cookie["httponly"], "refresh cookie is httpOnly")
        check.equal(
            int(cookie["max-age"]),
            int(lifetime.total_seconds()),
            "and lives as long as the refresh token",
        )


########################################################################
########################################################################
#
class TestCookieTokenRefreshView:
    """Tests for CookieTokenRefreshView -- reads refresh token from cookie."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "cookie_value",
        [
            pytest.param(None, id="no-cookie"),
            pytest.param("not.a.valid.jwt", id="invalid-cookie"),
        ],
    )
    def test_missing_or_invalid_cookie_returns_401(
        self, client: Client, cookie_value: str | None
    ) -> None:
        """
        GIVEN: a request with no refresh cookie or an invalid one
        WHEN:  POST /api/token/refresh/
        THEN:  the response status is 401
        """
        if cookie_value is not None:
            client.cookies[REFRESH_COOKIE_NAME] = cookie_value
        response = client.post(reverse("token-refresh"))
        assert response.status_code == 401

    ####################################################################
    #
    def test_refresh_issues_access_token_and_rotates_cookie(
        self, client: Client, user: User
    ) -> None:
        """
        GIVEN: a valid refresh token in the cookie and ROTATE_REFRESH_TOKENS=True
        WHEN:  POST /api/token/refresh/
        THEN:  the response is 200 with an `access` token that is a valid
               JWT for the user, and sets a new refresh cookie that
               differs from the original token
        """
        original = str(RefreshToken.for_user(user))
        client.cookies[REFRESH_COOKIE_NAME] = original

        response = client.post(reverse("token-refresh"))

        assert response.status_code == 200
        check.equal(
            int(UntypedToken(response.json()["access"])["user_id"]),
            user.pk,
            "access token is a valid JWT for the user",
        )
        assert REFRESH_COOKIE_NAME in response.cookies
        check.not_equal(
            response.cookies[REFRESH_COOKIE_NAME].value,
            original,
            "refresh cookie rotated",
        )

    ####################################################################
    #
    def test_expired_refresh_token_returns_401(
        self, client: Client, user: User, settings: LazySettings
    ) -> None:
        """
        GIVEN: a refresh token issued now
        WHEN:  POST /api/token/refresh/ after the token has expired
        THEN:  the response status is 401
        """
        refresh = RefreshToken.for_user(user)
        client.cookies[REFRESH_COOKIE_NAME] = str(refresh)

        lifetime = cast(
            timedelta, settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"]
        )
        future = datetime.now(tz=UTC) + lifetime + timedelta(seconds=1)
        with freeze_time(future):
            response = client.post(reverse("token-refresh"))

        assert response.status_code == 401


########################################################################
########################################################################
#
class TestCookieTokenLogoutView:
    """Tests for CookieTokenLogoutView -- server-side SPA sign-out."""

    ####################################################################
    #
    def test_logout_revokes_refresh_token_and_clears_cookie(
        self, client: Client, login_response: tuple[User, "Response"]
    ) -> None:
        """
        GIVEN: a user signed in through POST /api/token/
        WHEN:  POST /api/token/logout/
        THEN:  the response is 204 and expires the refresh cookie
         AND:  the refresh token that was in the cookie no longer
               refreshes
        """
        _, login = login_response
        refresh_token = login.cookies[REFRESH_COOKIE_NAME].value

        response = client.post(reverse("token-logout"))

        check.equal(response.status_code, 204, "no content")
        check.equal(
            response.cookies[REFRESH_COOKIE_NAME]["max-age"],
            0,
            "refresh cookie expired",
        )
        client.cookies[REFRESH_COOKIE_NAME] = refresh_token
        check.equal(
            client.post(reverse("token-refresh")).status_code,
            401,
            "revoked token does not refresh",
        )

    ####################################################################
    #
    @pytest.mark.parametrize(
        "cookie_value",
        [
            pytest.param(None, id="no-cookie"),
            pytest.param("not.a.valid.jwt", id="invalid-cookie"),
        ],
    )
    def test_missing_or_invalid_cookie_returns_204(
        self, client: Client, cookie_value: str | None
    ) -> None:
        """
        GIVEN: a request with no refresh cookie or an invalid one
        WHEN:  POST /api/token/logout/
        THEN:  the response is 204 and still expires the refresh cookie
        """
        if cookie_value is not None:
            client.cookies[REFRESH_COOKIE_NAME] = cookie_value

        response = client.post(reverse("token-logout"))

        check.equal(response.status_code, 204, "no content")
        check.equal(
            response.cookies[REFRESH_COOKIE_NAME]["max-age"],
            0,
            "refresh cookie expired",
        )


########################################################################
########################################################################
#
class TestSpaShellView:
    """Tests for SpaShellView -- serves the Vue SPA shell at /app/."""

    ####################################################################
    #
    @pytest.mark.parametrize("logged_in", [False, True], ids=["anon", "user"])
    @pytest.mark.parametrize(
        "path",
        [
            pytest.param("/app/", id="root"),
            pytest.param("/app/some/deep/route", id="deep-subpath"),
            pytest.param("/app/login/", id="login"),
        ],
    )
    def test_shell_returns_200(
        self,
        client: Client,
        user: User,
        vite_dev_mode: None,
        path: str,
        logged_in: bool,
    ) -> None:
        """
        GIVEN: a request with or without a Django session
        WHEN:  GET /app/ or any sub-path under /app/
        THEN:  the response status is 200 -- the SPA is self-authenticating
               and owns its own login UI, so Django does not gate /app/
        """
        if logged_in:
            client.force_login(user)

        assert client.get(path).status_code == 200
