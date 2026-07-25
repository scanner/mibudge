#!/usr/bin/env python
#
"""Fixtures for the credentials tests.

Registers the credentials factories and provides fixture factories that
build an APIClient carrying each kind of credential mibudge accepts, so
that behaviour shared by all of them (notably the
RequiresInteractiveAuth gate) can be parametrized over credential kind
instead of duplicated per credential.
"""

# system imports
from collections.abc import Callable

# 3rd party imports
import pytest
from pytest_factoryboy import register
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken as JWTRefreshToken

# Project imports
from credentials.models import AccessToken
from users.models import User

from .factories import (
    AccessTokenFactory,
    APIKeyFactory,
    ApplicationFactory,
    MintedAPIKey,
)

register(APIKeyFactory)  # APIKeyFactory -> api_key_factory fixture
register(ApplicationFactory)  # -> application_factory fixture
register(AccessTokenFactory)  # -> access_token_factory fixture

# The credential kinds `credential_client` knows how to build.  The two
# machine kinds are what the RequiresInteractiveAuth gate must reject;
# 'jwt' is the interactive session it must let through.
#
MACHINE_CREDENTIAL_KINDS = ["api_key", "oauth2"]


####################################################################
#
@pytest.fixture
def bearer_client() -> Callable[[str], APIClient]:
    """Return a factory for clients sending 'Authorization: Bearer <token>'.

    Returns:
        A callable taking a token string and returning an APIClient.
    """

    def _bearer_client(token: str) -> APIClient:
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return client

    return _bearer_client


####################################################################
#
@pytest.fixture
def api_key_client() -> Callable[[str], APIClient]:
    """Return a factory for clients sending 'Authorization: Api-Key <key>'.

    Returns:
        A callable taking a plaintext API key and returning an APIClient.
    """

    def _api_key_client(plaintext: str) -> APIClient:
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Api-Key {plaintext}")
        return client

    return _api_key_client


####################################################################
#
@pytest.fixture
def credential_client(
    api_key_factory: Callable[..., MintedAPIKey],
    access_token_factory: Callable[..., AccessToken],
    api_key_client: Callable[[str], APIClient],
    bearer_client: Callable[[str], APIClient],
) -> Callable[[str, User], APIClient]:
    """Return a factory for clients authenticated as a user by any means.

    Returns:
        A callable taking a credential kind ('api_key', 'oauth2', or
        'jwt') and a User, and returning an APIClient that authenticates
        as that user with a freshly minted credential of that kind.
    """

    def _credential_client(kind: str, user: User) -> APIClient:
        match kind:
            case "api_key":
                api_key = api_key_factory(user=user)
                return api_key_client(api_key.plaintext)
            case "oauth2":
                access_token = access_token_factory(user=user)
                return bearer_client(access_token.token)
            case "jwt":
                jwt = JWTRefreshToken.for_user(user).access_token
                return bearer_client(str(jwt))
            case _:
                raise ValueError(f"Unknown credential kind: {kind!r}")

    return _credential_client
