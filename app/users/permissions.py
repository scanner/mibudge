"""
DRF permissions for user/security endpoints.

Machine credentials (API keys today; OAuth2 tokens when phase 2 lands)
get blanket access to the budgeting domain but are denied on
user/security endpoints -- a blocklist enforced by attaching
RequiresInteractiveAuth to those views.  When fine-grained scopes are
introduced this gate becomes just another scope check.
"""

# 3rd party imports
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

# Project imports
from users.models import APIKey


########################################################################
########################################################################
#
class RequiresInteractiveAuth(BasePermission):
    """Deny requests authenticated with a machine credential.

    Interactive sessions (JWT from a password login) carry a
    rest_framework_simplejwt token in ``request.auth``; machine
    credentials carry an APIKey instance (and later an OAuth2 access
    token).  Apply this alongside the view's normal permissions on
    sensitive endpoints: password/email change, invitations, user
    management, and API-key management itself.
    """

    message = (
        "This endpoint requires an interactive login session; "
        "machine credentials such as API keys are not permitted."
    )

    ####################################################################
    #
    def has_permission(self, request: Request, view: APIView) -> bool:
        """Return False when the request was authenticated by an API key.

        Args:
            request: The incoming DRF request.
            view: The view being accessed.

        Returns:
            True unless the request's credential is a machine credential.
        """
        return not isinstance(request.auth, APIKey)
