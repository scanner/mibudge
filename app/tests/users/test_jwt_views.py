"""Tests for JWT-related auth views: SpaLoginView and CookieTokenRefreshView."""

# system imports
#
import re
from datetime import UTC, datetime, timedelta
from typing import cast

# 3rd party imports
#
import pytest
from django.conf import LazySettings
from django.test import Client
from django.urls import reverse
from django_vite.core.asset_loader import DjangoViteAssetLoader
from freezegun import freeze_time
from rest_framework_simplejwt.tokens import RefreshToken, UntypedToken

# app imports
#
from users.models import User
from users.views import REFRESH_COOKIE_NAME

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


########################################################################
########################################################################
#
class TestSpaLoginView:
    """Tests for SpaLoginView -- the allauth → SPA JWT handoff."""

    ####################################################################
    #
    def test_unauthenticated_redirects_to_login(self, client: Client) -> None:
        """
        GIVEN: an unauthenticated request
        WHEN:  GET /users/~spa-login/
        THEN:  the response is a redirect to the login page
        """
        response = client.get(reverse("users:spa-login"))
        assert response.status_code == 302
        assert "/accounts/login/" in response["Location"]

    ####################################################################
    #
    def test_sets_httponly_refresh_cookie(
        self, client: Client, user: User
    ) -> None:
        """
        GIVEN: an authenticated user
        WHEN:  GET /users/~spa-login/
        THEN:  the response sets an httpOnly cookie named REFRESH_COOKIE_NAME
        """
        client.force_login(user)
        response = client.get(reverse("users:spa-login"))
        assert REFRESH_COOKIE_NAME in response.cookies
        assert response.cookies[REFRESH_COOKIE_NAME]["httponly"]

    ####################################################################
    #
    def test_refresh_cookie_max_age_matches_jwt_lifetime(
        self, client: Client, user: User, settings: LazySettings
    ) -> None:
        """
        GIVEN: an authenticated user
        WHEN:  GET /users/~spa-login/
        THEN:  the refresh cookie's max-age matches SIMPLE_JWT REFRESH_TOKEN_LIFETIME
        """
        client.force_login(user)
        response = client.get(reverse("users:spa-login"))
        lifetime = cast(
            timedelta, settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"]
        )
        cookie = response.cookies[REFRESH_COOKIE_NAME]
        assert int(cookie["max-age"]) == int(lifetime.total_seconds())

    ####################################################################
    #
    def test_embedded_access_token_is_valid_jwt_for_user(
        self, client: Client, user: User
    ) -> None:
        """
        GIVEN: an authenticated user
        WHEN:  GET /users/~spa-login/
        THEN:  the page contains a window.__INITIAL_TOKEN__ assignment whose
               value is a valid JWT with a user_id claim matching the user
        """
        client.force_login(user)
        response = client.get(reverse("users:spa-login"))
        content = response.content.decode()

        match = re.search(r'window\.__INITIAL_TOKEN__ = "([^"]+)"', content)
        assert match is not None, "Access token not found in page"

        # simplejwt stubs incorrectly type UntypedToken(token) as Token | None;
        # it accepts a raw string at runtime — revisit if stubs improve
        token = UntypedToken(str(match.group(1)))  # type: ignore[arg-type]
        assert int(token["user_id"]) == user.pk


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
    def test_returned_access_token_is_valid_jwt_for_user(
        self, client: Client, user: User
    ) -> None:
        """
        GIVEN: a valid refresh token in the cookie
        WHEN:  POST /api/token/refresh/
        THEN:  the response is 200 with an ``access`` token that is a valid
               JWT whose user_id claim matches the authenticated user
        """
        refresh = RefreshToken.for_user(user)
        client.cookies[REFRESH_COOKIE_NAME] = str(refresh)
        response = client.post(reverse("token-refresh"))
        assert response.status_code == 200
        token = UntypedToken(response.json()["access"])
        assert int(token["user_id"]) == user.pk

    ####################################################################
    #
    def test_token_rotation_updates_refresh_cookie(
        self, client: Client, user: User
    ) -> None:
        """
        GIVEN: a valid refresh token in the cookie and ROTATE_REFRESH_TOKENS=True
        WHEN:  POST /api/token/refresh/
        THEN:  the response sets a new refresh cookie that differs from the
               original token
        """
        refresh = RefreshToken.for_user(user)
        original = str(refresh)
        client.cookies[REFRESH_COOKIE_NAME] = original
        response = client.post(reverse("token-refresh"))
        assert response.status_code == 200
        assert REFRESH_COOKIE_NAME in response.cookies
        assert response.cookies[REFRESH_COOKIE_NAME].value != original

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
class TestSpaShellView:
    """Tests for SpaShellView -- serves the Vue SPA shell at /app/."""

    ####################################################################
    #
    def test_unauthenticated_redirects_to_login(self, client: Client) -> None:
        """
        GIVEN: an unauthenticated request
        WHEN:  GET /app/
        THEN:  the response is a redirect to the login page
        """
        response = client.get("/app/")
        assert response.status_code == 302
        assert "/accounts/login/" in response["Location"]

    ####################################################################
    #
    @pytest.mark.parametrize(
        "path",
        [
            pytest.param("/app/", id="root"),
            pytest.param("/app/dashboard/", id="subpath"),
            pytest.param("/app/some/deep/route", id="deep-subpath"),
        ],
    )
    def test_authenticated_returns_200(
        self,
        client: Client,
        user: User,
        vite_dev_mode: None,
        path: str,
    ) -> None:
        """
        GIVEN: an authenticated user
        WHEN:  GET /app/ or any sub-path under /app/
        THEN:  the response status is 200
        """
        client.force_login(user)
        response = client.get(path)
        assert response.status_code == 200
