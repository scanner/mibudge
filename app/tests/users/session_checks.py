"""Check whether a JWT refresh token is still a live session."""

# 3rd party imports
from django.test import Client
from django.urls import reverse
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

# Project imports
from users.views import REFRESH_COOKIE_NAME


####################################################################
#
def session_valid(refresh: RefreshToken | str) -> bool:
    """True if the refresh token still produces an access token."""
    client = Client()
    client.cookies[REFRESH_COOKIE_NAME] = str(refresh)
    return (
        client.post(reverse("token-refresh")).status_code == status.HTTP_200_OK
    )
