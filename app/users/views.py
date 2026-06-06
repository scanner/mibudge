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
from django.http import HttpRequest, HttpResponseRedirect
from django.shortcuts import redirect
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

# Project imports
#
from users.email_change import (
    SPA_EMAIL_CHANGE_CONFIRMED,
    SPA_EMAIL_CHANGE_ERROR,
    SPA_EMAIL_CHANGE_REVOKED,
    AlreadyConfirmedError,
    AlreadyRevokedError,
    EmailAlreadyTakenError,
    RevocationWindowClosedError,
    TokenExpiredError,
    TokenNotFoundError,
    confirm_request,
    revoke_request,
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


########################################################################
########################################################################
#
# Email-change browser views
#
# These views are the GET handlers for the links embedded in the two
# email-change notification emails.  They process the action and redirect
# the user's browser to an SPA result page.
#
# Native mobile apps that have registered mibudge.money as a Universal
# Link (iOS) or App Link (Android) will intercept these URLs before the
# browser opens them and call the corresponding REST API endpoints instead:
#
#   POST /api/v1/users/me/change-email/<token>/confirm/
#   POST /api/v1/users/me/change-email/<token>/revoke/
#
# Both the browser path (here) and the API path share the same service
# functions in users.email_change, so business logic lives in one place.
#
########################################################################
########################################################################
#
def email_change_confirm_view(
    request: HttpRequest, token: str
) -> HttpResponseRedirect:
    """Process a new-address verification link and redirect to the SPA.

    Called when a user clicks the confirmation link sent to their new
    email address.  On success the email is updated and the browser is
    sent to the 'confirmed' SPA result page.  Any error condition sends
    the browser to the 'error' result page with a ``reason`` query param
    so the SPA can display a meaningful message.
    """
    try:
        confirm_request(token)
        return redirect(SPA_EMAIL_CHANGE_CONFIRMED)
    except AlreadyConfirmedError:
        return redirect(f"{SPA_EMAIL_CHANGE_ERROR}?reason=already_confirmed")
    except AlreadyRevokedError:
        return redirect(f"{SPA_EMAIL_CHANGE_ERROR}?reason=revoked")
    except TokenExpiredError:
        return redirect(f"{SPA_EMAIL_CHANGE_ERROR}?reason=expired")
    except EmailAlreadyTakenError:
        return redirect(f"{SPA_EMAIL_CHANGE_ERROR}?reason=email_taken")
    except TokenNotFoundError:
        return redirect(f"{SPA_EMAIL_CHANGE_ERROR}?reason=invalid")


########################################################################
########################################################################
#
def email_change_revoke_view(
    request: HttpRequest, token: str
) -> HttpResponseRedirect:
    """Process a 'this wasn't me' revocation link and redirect to the SPA.

    Called when a user clicks the revocation link sent to their old email
    address.  On success the email is reverted, all sessions are
    invalidated, and the browser is sent to the 'revoked' SPA result page.
    """
    try:
        revoke_request(token)
        return redirect(SPA_EMAIL_CHANGE_REVOKED)
    except AlreadyRevokedError:
        return redirect(f"{SPA_EMAIL_CHANGE_ERROR}?reason=already_revoked")
    except RevocationWindowClosedError:
        return redirect(f"{SPA_EMAIL_CHANGE_ERROR}?reason=window_closed")
    except TokenNotFoundError:
        return redirect(f"{SPA_EMAIL_CHANGE_ERROR}?reason=invalid")
