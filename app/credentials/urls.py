#!/usr/bin/env python
#
"""
OAuth2 provider endpoints.

A curated subset of django-oauth-toolkit's urlpatterns -- DOT's own
``oauth2_provider.urls`` is deliberately NOT included wholesale:

- *Device flow* (device-authorization/, device/, device-confirm/,
  device-grant-status/) is part of DOT's base patterns but RFC 8628 is
  deferred; mounting the endpoints would advertise a flow this server
  does not support.  Adding them later is purely additive.
- *Application/token management* (applications/, authorized_tokens/) are
  DOT's own HTML CRUD screens.  mibudge serves those from the SPA
  against its REST API instead, so DOT's would be a second, unstyled,
  session-authenticated management surface.
- *OIDC* (userinfo/, jwks.json, RP-initiated logout) is not offered:
  this is an OAuth2 authorization server, not an identity provider.
- *Dynamic client registration* (RFC 7591) is not offered: apps are
  registered by a user or promoted by staff, which is the whole point of
  the registration/visibility model.
- *Token introspection* is not offered: it exists so a separate resource
  server can validate a token issued elsewhere, and here the
  authorization server and the resource server are the same process.
- *RFC 9728 protected-resource metadata* is deferred to the MCP
  end-to-end work, which is where its identifier/name settings can be
  set to something real and verified against a client.

IMPORTANT: two constraints shape this module.

1. The namespace must stay ``oauth2_provider``.  DOT reverses its own
   URL names internally -- the RFC 8414 metadata view builds the
   discovery document with ``reverse("oauth2_provider:authorize")`` and
   friends -- so renaming it would silently drop endpoints from
   discovery.  That same reverse() is what keeps the unmounted
   device-flow endpoints out of the document automatically.
2. This module is mounted at the site ROOT, not under /o/, because RFC
   8414 puts the discovery document at the origin's
   /.well-known/oauth-authorization-server.  The /o/ prefix is therefore
   spelled out on the individual endpoints below.  Mounting the metadata
   separately is not an option: a second include with the same namespace
   would shadow the first, and reverse() would stop finding half of it.
"""

# 3rd party imports
from django.urls import path
from oauth2_provider import views as oauth2_views

# Project imports
from credentials.views import OAuth2AuthorizationView, OAuth2LoginView

app_name = "oauth2_provider"

urlpatterns = [
    # RFC 8414 authorization-server metadata.  Must live at the origin
    # root; this is how an MCP client discovers the endpoints below.
    path(
        ".well-known/oauth-authorization-server",
        oauth2_views.OAuthServerMetadataView.as_view(),
        name="oauth-server-metadata",
    ),
    # Consent screen.  Subclassed only to redirect unauthenticated users
    # to the login below instead of the SPA -- see credentials/views.py.
    path("o/authorize/", OAuth2AuthorizationView.as_view(), name="authorize"),
    path("o/token/", oauth2_views.TokenView.as_view(), name="token"),
    path(
        "o/revoke_token/",
        oauth2_views.RevokeTokenView.as_view(),
        name="revoke-token",
    ),
    # Server-rendered login for this flow only.  NOT the SPA's login and
    # not a general-purpose one: it exists because the consent screen
    # needs a Django session.
    path("o/login/", OAuth2LoginView.as_view(), name="login"),
]
