#
# Project-level views -- thin wrappers that don't belong to a specific app.
#

# 3rd party imports
#
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

# app imports
#


########################################################################
########################################################################
#
class SpaShellView(LoginRequiredMixin, TemplateView):
    """
    Serves the Vue SPA shell for /app/ and any sub-path under it.

    The template loads the Vite-built bundle (or connects to the Vite dev
    server in development). All further routing is handled client-side by
    Vue Router -- the server never sees sub-routes.
    """

    template_name = "spa/shell.html"


spa_shell_view = SpaShellView.as_view()
