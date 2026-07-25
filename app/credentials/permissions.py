"""
DRF permissions gating machine credentials off user/security endpoints.

Machine credentials (API keys and OAuth2 access tokens) get blanket
access to the budgeting domain but are denied on user/security
endpoints -- a blocklist enforced by attaching RequiresInteractiveAuth
to those views.  Views whose reads are useful to machine consumers
(e.g. /users/me/, which the importers query for the user's timezone)
use RequiresInteractiveAuthForWrites instead, which gates only the
mutating methods.  When fine-grained scopes are introduced these gates
become just another scope check.
"""

# 3rd party imports
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

# Project imports
from credentials.models import AccessToken, APIKey

# The credential types that identify a request as machine-driven, keyed
# off what each authenticator puts in ``request.auth``:
# ApiKeyAuthentication -> APIKey, DOT's OAuth2Authentication ->
# AccessToken.  Interactive sessions carry a simplejwt token instead
# (and force_authenticate() in tests carries None).
#
# IMPORTANT: this is a blocklist, so it fails OPEN -- a new machine
# credential type that is not listed here silently gains access to every
# gated endpoint.  Any authenticator added to
# DEFAULT_AUTHENTICATION_CLASSES must be classified here.
#
MACHINE_CREDENTIAL_TYPES = (APIKey, AccessToken)


########################################################################
########################################################################
#
class RequiresInteractiveAuth(BasePermission):
    """Deny requests authenticated with a machine credential.

    Interactive sessions (JWT from a password login) carry a
    rest_framework_simplejwt token in ``request.auth``; machine
    credentials carry an APIKey or an OAuth2 AccessToken (see
    MACHINE_CREDENTIAL_TYPES).  Apply this alongside the view's normal
    permissions on sensitive endpoints: password/email change,
    invitations, user management, and API-key management itself.

    NOTE: an OAuth2 grant is denied here no matter what scopes it
    carries.  A 3rd-party app must never be able to change the login
    email or password of the account that authorized it -- that would
    let a granted app lock the user out of revoking the grant.
    """

    message = (
        "This endpoint requires an interactive login session; "
        "machine credentials such as API keys and OAuth2 tokens are "
        "not permitted."
    )

    ####################################################################
    #
    def has_permission(self, request: Request, view: APIView) -> bool:
        """Return False when a machine credential authenticated the request.

        Args:
            request: The incoming DRF request.
            view: The view being accessed.

        Returns:
            True unless the request's credential is a machine credential.
        """
        return not isinstance(request.auth, MACHINE_CREDENTIAL_TYPES)


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
