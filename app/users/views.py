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
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import DetailView, RedirectView, UpdateView
from rest_framework import status
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

# app imports
#

User = get_user_model()

########################################################################
########################################################################
#
# Cookie name used for the httpOnly refresh token throughout the auth flow.
# Defined here so SpaLoginView and CookieTokenRefreshView stay in sync.
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
class SpaLoginView(LoginRequiredMixin, View):
    """
    Post-login handoff from allauth to the Vue SPA.

    allauth authenticates the user and redirects here (LOGIN_REDIRECT_URL).
    This view issues a JWT pair: the refresh token goes into an httpOnly
    cookie; the access token is injected into the page as
    window.__INITIAL_TOKEN__ so the SPA can read it once on load.
    """

    ####################################################################
    #
    def get(self, request: HttpRequest) -> HttpResponse:
        # LoginRequiredMixin guarantees an authenticated user; django-stubs
        # cannot narrow AbstractBaseUser | AnonymousUser -- cast is safe here.
        refresh = RefreshToken.for_user(cast(AbstractBaseUser, request.user))

        response = render(
            request,
            "spa/token_handoff.html",
            {"access_token": str(refresh.access_token)},
        )
        lifetime = cast(
            timedelta, settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"]
        )
        response.set_cookie(
            REFRESH_COOKIE_NAME,
            str(refresh),
            max_age=int(lifetime.total_seconds()),
            httponly=True,
            secure=not settings.DEBUG,
            samesite="Strict",
        )
        return response


spa_login_view = SpaLoginView.as_view()


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
            lifetime = cast(
                timedelta, settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"]
            )
            response.set_cookie(
                REFRESH_COOKIE_NAME,
                validated["refresh"],
                max_age=int(lifetime.total_seconds()),
                httponly=True,
                secure=not settings.DEBUG,
                samesite="Strict",
            )

        return response


cookie_token_refresh_view = CookieTokenRefreshView.as_view()
