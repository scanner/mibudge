# system imports
#
from datetime import timedelta
from typing import cast

# 3rd party imports
#
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import AbstractBaseUser
from django.contrib.messages.views import SuccessMessageMixin
from django.http import HttpRequest
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, RedirectView, UpdateView
from rest_framework import status
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

# app imports
#

User = get_user_model()

########################################################################
########################################################################
#
# Cookie name used for the httpOnly refresh token throughout the auth flow.
# Shared by CookieTokenObtainPairView and CookieTokenRefreshView.
#
REFRESH_COOKIE_NAME = "refresh_token"


########################################################################
########################################################################
#
class UserDetailView(LoginRequiredMixin, DetailView):
    model = User
    slug_field = "username"
    slug_url_kwarg = "username"


user_detail_view = UserDetailView.as_view()


########################################################################
########################################################################
#
class UserUpdateView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = User
    fields = ["name"]
    success_message = _("Information successfully updated")

    ####################################################################
    #
    def get_success_url(self) -> str:
        # LoginRequiredMixin guarantees an authenticated user, but django-stubs
        # types request.user as AbstractBaseUser | AnonymousUser and cannot
        # narrow it -- revisit if django-stubs improves
        return self.request.user.get_absolute_url()  # type: ignore[union-attr]

    ####################################################################
    #
    def get_object(self, queryset=None) -> AbstractBaseUser:
        return self.request.user  # type: ignore[return-value]


user_update_view = UserUpdateView.as_view()


########################################################################
########################################################################
#
class UserRedirectView(LoginRequiredMixin, RedirectView):
    permanent = False

    ####################################################################
    #
    def get_redirect_url(self) -> str:
        return reverse(
            "users:detail", kwargs={"username": self.request.user.username}
        )


user_redirect_view = UserRedirectView.as_view()


########################################################################
########################################################################
#
def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    """Attach the httpOnly refresh cookie to ``response``."""
    lifetime = cast(timedelta, settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"])
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        refresh_token,
        max_age=int(lifetime.total_seconds()),
        httponly=True,
        secure=not settings.DEBUG,
        samesite="Strict",
    )


########################################################################
########################################################################
#
class CookieTokenObtainPairView(TokenObtainPairView):
    """
    JWT obtain endpoint that stores the refresh token in an httpOnly
    cookie and returns only the access token in the response body.

    This is the browser-SPA login flow: JS receives the short-lived
    access token (kept in memory); the refresh token is a
    Secure/HttpOnly/SameSite=Strict cookie that JS cannot read,
    and that the browser sends automatically to /api/token/refresh/.
    """

    ####################################################################
    #
    def post(
        self, request: HttpRequest, *args: object, **kwargs: object
    ) -> Response:
        response = super().post(request, *args, **kwargs)
        if response.status_code == status.HTTP_200_OK and isinstance(
            response.data, dict
        ):
            refresh = response.data.pop("refresh", None)
            if refresh:
                _set_refresh_cookie(response, refresh)
        return response


cookie_token_obtain_pair_view = CookieTokenObtainPairView.as_view()


########################################################################
########################################################################
#
class CookieTokenRefreshView(TokenRefreshView):
    """
    JWT refresh endpoint that reads the refresh token from the httpOnly
    cookie rather than the request body.

    On success, returns {"access": "<new_access_token>"} in JSON.
    When token rotation is enabled, also rotates the refresh cookie so
    the 14-day sliding window resets with each use.
    """

    ####################################################################
    #
    def post(
        self, request: HttpRequest, *args: object, **kwargs: object
    ) -> Response:
        refresh_token = request.COOKIES.get(REFRESH_COOKIE_NAME)
        if not refresh_token:
            return Response(
                {"detail": "No refresh token cookie."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Pass the cookie value directly to the serializer -- avoids
        # mutating request.data which may be immutable.
        serializer = self.get_serializer(data={"refresh": refresh_token})
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as e:
            raise InvalidToken(e.args[0]) from e

        validated = serializer.validated_data
        response = Response({"access": validated["access"]})

        if "refresh" in validated:
            # Rotation produced a new refresh token -- update the cookie.
            _set_refresh_cookie(response, validated["refresh"])

        return response


cookie_token_refresh_view = CookieTokenRefreshView.as_view()
