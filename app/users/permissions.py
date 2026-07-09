"""
DRF permissions for user/security endpoints.

Machine credentials (API keys today; OAuth2 tokens when phase 2 lands)
get blanket access to the budgeting domain but are denied on
user/security endpoints -- a blocklist enforced by attaching
RequiresInteractiveAuth to those views.  Views whose reads are useful
to machine consumers (e.g. /users/me/, which the importers query for
the user's timezone) use RequiresInteractiveAuthForWrites instead,
which gates only the mutating methods.  When fine-grained scopes are
introduced these gates become just another scope check.
"""

# 3rd party imports
from rest_framework.permissions import SAFE_METHODS, BasePermission
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


########################################################################
########################################################################
#
class RequiresInteractiveAuthForWrites(RequiresInteractiveAuth):
    """Deny machine-credential requests only for mutating methods.

    Read-only variant of RequiresInteractiveAuth for user-domain views
    whose GET responses are legitimately useful to machine consumers
    (the importers read `timezone` from /users/me/) but whose writes
    must stay interactive-only.
    """

    ####################################################################
    #
    def has_permission(self, request: Request, view: APIView) -> bool:
        """Return False for machine-credential requests that mutate.

        Args:
            request: The incoming DRF request.
            view: The view being accessed.

        Returns:
            True for safe (read-only) methods regardless of credential;
            otherwise defers to RequiresInteractiveAuth.
        """
        if request.method in SAFE_METHODS:
            return True
        return super().has_permission(request, view)
