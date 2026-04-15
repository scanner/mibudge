#
# Project-level views -- thin wrappers that don't belong to a specific app.
#

# 3rd party imports
#
from django.views.generic import TemplateView

# app imports
#


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
    """

    template_name = "spa/shell.html"


spa_shell_view = SpaShellView.as_view()
