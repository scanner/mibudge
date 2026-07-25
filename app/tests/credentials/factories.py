#!/usr/bin/env python
#
"""factory-boy factories for the credentials app.

Registered as fixtures in tests/credentials/conftest.py -- always use
the ``*_factory`` fixtures in tests rather than these classes directly.
"""

# system imports
from datetime import timedelta
from typing import TYPE_CHECKING, Any

# 3rd party imports
import factory
from django.utils import timezone
from factory.django import DjangoModelFactory
from oauthlib.common import generate_token

# Project imports
from credentials.models import AccessToken, APIKey, Application
from tests.users.factories import UserFactory

if TYPE_CHECKING:
    # The APIKey that APIKeyFactory hands back carries the one-time
    # plaintext (see the factory docstring).  Declaring that as a
    # type-check-only subclass keeps `plaintext` off the real model --
    # a persisted plaintext field on a credential is exactly what the
    # hash-only design avoids -- while letting tests stay typed.  Django
    # never sees this class, so it registers no model and needs no
    # migration.
    class MintedAPIKey(APIKey):
        plaintext: str

else:
    MintedAPIKey = APIKey


########################################################################
####################################################################
#
class APIKeyFactory(DjangoModelFactory):
    """Build an APIKey with real key material.

    NOTE: creation goes through ``APIKey.make()`` rather than
    ``objects.create()`` so the hash and displayable prefix are derived
    the same way they are in production.  ``make()`` returns the
    plaintext exactly once and it is never recoverable from the row, so
    it is stashed on the returned instance as ``plaintext`` for tests
    that need to authenticate with the key.
    """

    class Meta:
        model = APIKey

    user = factory.SubFactory(UserFactory)
    name = factory.Sequence(lambda n: f"test key {n}")
    expires_at = None

    ####################################################################
    #
    @classmethod
    def _create(
        cls, model_class: type[APIKey], *args: Any, **kwargs: Any
    ) -> "MintedAPIKey":
        """Mint the key via APIKey.make(), keeping the plaintext."""
        api_key, plaintext = model_class.make(**kwargs)
        # `plaintext` is not a model field -- see the class docstring.
        api_key.plaintext = plaintext  # type: ignore[attr-defined]
        return api_key  # type: ignore[return-value]


########################################################################
####################################################################
#
class ApplicationFactory(DjangoModelFactory):
    """Build a registered OAuth2 application.

    Defaults match the only client shape mibudge issues tokens to: a
    public client (no secret) using the authorization-code grant, which
    settings.OAUTH2_PROVIDER then requires PKCE for.
    """

    class Meta:
        model = Application

    name = factory.Sequence(lambda n: f"test app {n}")
    user = factory.SubFactory(UserFactory)
    client_type = Application.CLIENT_PUBLIC
    authorization_grant_type = Application.GRANT_AUTHORIZATION_CODE
    redirect_uris = "https://example.com/callback"


########################################################################
####################################################################
#
class AccessTokenFactory(DjangoModelFactory):
    """Build an OAuth2 access token, valid for an hour by default.

    Pass ``expires`` in the past to build an expired token.  The owning
    application defaults to one registered by a *different* user, which
    is the normal case: the app's owner registered it, the token's user
    authorized it.
    """

    class Meta:
        model = AccessToken

    user = factory.SubFactory(UserFactory)
    application = factory.SubFactory(ApplicationFactory)
    token = factory.LazyFunction(generate_token)
    expires = factory.LazyFunction(lambda: timezone.now() + timedelta(hours=1))
    scope = "read write"
