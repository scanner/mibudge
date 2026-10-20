#
# Project-level views -- thin wrappers that don't belong to a specific app.
#

# 3rd party imports
#
from django.conf import settings
from django.db import transaction
from django.views.decorators.cache import cache_control
from django.views.generic import TemplateView
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

# app imports
#

# The REST API versions this server serves, each mounted at `/api/<v>/`.
#
API_VERSIONS = ["v1"]


########################################################################
########################################################################
#
class SpaShellView(TemplateView):
    """
    Serves the Vue SPA shell for /app/ and any sub-path under it.

    The SPA owns its own auth flow: on cold boot it attempts a silent
    refresh via the httpOnly refresh cookie and, failing that, shows its
    own login screen (/app/login/). This matches what a future native
    iOS/iPadOS/macOS/visionOS client would need, so the server shell is
    intentionally unauthenticated.

    The template loads the Vite-built bundle (or connects to the Vite dev
    server in development). All further routing is handled client-side by
    Vue Router -- the server never sees sub-routes.

    The shell is sent with `Cache-Control: no-cache, max-age=0`, so every
    page load asks the server for it and gets the current release's
    asset names.  The hashed assets themselves are cached as immutable.
    """

    template_name = "spa/shell.html"


spa_shell_view = cache_control(no_cache=True, max_age=0)(SpaShellView.as_view())


########################################################################
########################################################################
#
class HomeView(TemplateView):
    """Landing page served at /."""

    template_name = "pages/home.html"


home_view = HomeView.as_view()


########################################################################
########################################################################
#
class ServerVersionSerializer(serializers.Serializer):
    """The release a server runs and the API versions it serves."""

    version = serializers.CharField(
        help_text="The release the server runs, e.g. '0.4.1'."
    )
    api_versions = serializers.ListField(
        child=serializers.CharField(),
        help_text="The API versions served, each at '/api/<version>/'.",
    )


########################################################################
#
@extend_schema(
    tags=["meta"],
    summary="Get the server version",
    description=(
        "Return the release the server runs and the API versions it "
        "serves.  Needs no credentials, and ignores any that are sent."
    ),
    responses={200: ServerVersionSerializer},
)
# A read-only view: `ATOMIC_REQUESTS` would open a transaction, which
# on SQLite takes the database write lock (see
# `common.views.AtomicWritesMixin`).
#
@transaction.non_atomic_requests
@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def server_version(request: Request) -> Response:
    """Return the running release and the API versions served."""
    return Response(
        {"version": settings.MIBUDGE_VERSION, "api_versions": API_VERSIONS}
    )
