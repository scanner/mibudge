from datetime import timedelta

from allauth.account.internal.flows.password_change import (
    change_password as allauth_change_password,
)
from allauth.account.signals import password_changed
from django.contrib.auth import get_user_model
from django.utils import timezone
from drf_spectacular.utils import (
    OpenApiParameter,
    extend_schema,
    extend_schema_view,
)
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.mixins import (
    ListModelMixin,
    RetrieveModelMixin,
    UpdateModelMixin,
)
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from moneypools.api.v1.serializers import BankAccountInvitationSerializer
from moneypools.models import BankAccountInvitation
from users.email_change import (
    AlreadyConfirmedError,
    AlreadyRevokedError,
    EmailAlreadyTakenError,
    RevocationWindowClosedError,
    RevocationWindowOpenError,
    TokenExpiredError,
    TokenNotFoundError,
    confirm_request,
    create_request,
    revoke_request,
)
from users.models import APIKey
from users.permissions import (
    RequiresInteractiveAuth,
    RequiresInteractiveAuthForWrites,
)

from .serializers import (
    APIKeyCreatedSerializer,
    APIKeyCreateSerializer,
    APIKeySerializer,
    ChangePasswordSerializer,
    EmailChangeRequestSerializer,
    UserSerializer,
)

User = get_user_model()


@extend_schema_view(
    list=extend_schema(
        summary="List users (staff only)",
        description=("Return all users. Restricted to staff/admin users."),
    ),
    retrieve=extend_schema(
        summary="Get user details (staff only)",
        description=(
            "Return a single user by username. Restricted to staff/admin users."
        ),
    ),
    update=extend_schema(
        summary="Update a user (staff only)",
        description=(
            "Full update of a user profile. Restricted to staff/admin users."
        ),
    ),
    partial_update=extend_schema(
        summary="Partially update a user (staff only)",
        description=(
            "Partial update of a user profile. Restricted to staff/admin users."
        ),
    ),
)
class UserViewSet(
    RetrieveModelMixin, ListModelMixin, UpdateModelMixin, GenericViewSet
):
    """User profiles. List/retrieve/update restricted to staff; 'me' open to all."""

    serializer_class = UserSerializer
    queryset = User.objects.all()
    lookup_field = "username"
    permission_classes = [IsAdminUser, RequiresInteractiveAuth]
    filter_backends = [OrderingFilter]
    ordering_fields = ["username", "name"]
    ordering = ["username"]

    ####################################################################
    #
    def get_queryset(self, *args, **kwargs):
        qs = super().get_queryset()
        # Staff see all users; non-staff only reach here via the 'me'
        # action, which is filtered to the requesting user.
        #
        if not self.request.user.is_staff:
            return qs.filter(id=self.request.user.id)
        return qs

    ####################################################################
    #
    @extend_schema(
        summary="Get or update current user profile",
        description=(
            "GET returns the authenticated user's own profile. "
            "PATCH allows updating the name field. "
            "Available to any authenticated user (not restricted to "
            "staff). GET is also available to machine credentials "
            "(API keys) -- importers read the timezone field; PATCH "
            "requires an interactive login session."
        ),
    )
    @action(
        detail=False,
        methods=["GET", "PATCH"],
        permission_classes=[IsAuthenticated, RequiresInteractiveAuthForWrites],
    )
    def me(self, request):
        """Return or partially update the authenticated user's own profile."""
        if request.method == "PATCH":
            serializer = UserSerializer(
                request.user,
                data=request.data,
                partial=True,
                context={"request": request},
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(status=status.HTTP_200_OK, data=serializer.data)
        serializer = UserSerializer(request.user, context={"request": request})
        return Response(status=status.HTTP_200_OK, data=serializer.data)

    ####################################################################
    #
    @extend_schema(
        summary="Change current user's password",
        description=(
            "Change the authenticated user's password. "
            "Requires the current password for verification. "
            "The new password must score at least 2 on the zxcvbn scale. "
            "Existing JWT tokens remain valid; the caller may silently refresh "
            "as normal -- no forced re-login is imposed."
        ),
        request=ChangePasswordSerializer,
        responses={204: None},
    )
    @action(
        detail=False,
        methods=["POST"],
        url_path="me/change-password",
        permission_classes=[IsAuthenticated, RequiresInteractiveAuth],
    )
    def change_password(self, request):
        """Change the authenticated user's password.

        Returns 204 on success.  Returns 400 if the user has no usable
        password set, if the current password is wrong, or if the new
        password fails zxcvbn validation.
        """
        user = request.user
        if not user.has_usable_password():
            return Response(
                {"detail": "Set a password before changing it."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = ChangePasswordSerializer(
            data=request.data,
            context={"user": user},
        )
        serializer.is_valid(raise_exception=True)
        if not user.check_password(
            serializer.validated_data["current_password"]
        ):
            return Response(
                {"current_password": "Current password is incorrect."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        allauth_change_password(user, serializer.validated_data["new_password"])
        # allauth's change_password() only sets the password; it does not
        # dispatch the signal.  We dispatch it here so the notification
        # handler in users/signals.py fires.
        password_changed.send(
            sender=user.__class__,
            request=request,
            user=user,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    ####################################################################
    #
    @extend_schema(
        summary="Request an email address change",
        description=(
            "Initiate a self-service email change.  Sends a verification "
            "link to the new address and a revocation link to the old "
            "address.  Returns 403 if the user has no usable password; "
            "409 if new_email is already taken or a revocation window is "
            "currently open for this account."
        ),
        request=EmailChangeRequestSerializer,
        responses={201: None},
    )
    @action(
        detail=False,
        methods=["POST"],
        url_path="me/change-email",
        permission_classes=[IsAuthenticated, RequiresInteractiveAuth],
    )
    def change_email(self, request):
        """Initiate an email-address change for the authenticated user."""
        if not request.user.has_usable_password():
            return Response(
                {"detail": "Set a password before changing your email."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = EmailChangeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_email = serializer.validated_data["new_email"]
        try:
            create_request(request.user, new_email)
        except EmailAlreadyTakenError:
            return Response(
                {"new_email": "This email address is already in use."},
                status=status.HTTP_409_CONFLICT,
            )
        except RevocationWindowOpenError:
            return Response(
                {
                    "detail": (
                        "An email change is already in progress for this "
                        "account.  Please wait for the revocation window to "
                        "close before requesting another change."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )
        return Response(status=status.HTTP_201_CREATED)

    ####################################################################
    #
    @extend_schema(
        summary="Confirm an email address change (new-address token)",
        description=(
            "Verify a pending email change using the token from the "
            "verification link sent to the new address.  No authentication "
            "required -- the token is the credential.\n\n"
            "**Dual-path note:** The email link points to a Django GET view "
            "at ``/users/email-change/{token}/confirm/`` which processes the "
            "action and redirects the browser to the SPA result page.  "
            "Native apps that register mibudge.money as a Universal Link "
            "(iOS) or App Link (Android) intercept that URL and call this "
            "endpoint instead, receiving JSON and controlling their own UI."
        ),
        parameters=[
            OpenApiParameter(
                "token",
                str,
                OpenApiParameter.PATH,
                description="The email-change verification token.",
            ),
        ],
        request=None,
        responses={200: None},
    )
    @action(
        detail=False,
        methods=["POST"],
        url_path=r"me/change-email/(?P<token>[^/.]+)/confirm",
        permission_classes=[AllowAny],
    )
    def change_email_confirm(self, request, token=None):
        """Confirm an email-change request (new-address token, no auth required)."""
        try:
            confirm_request(token)
            return Response(status=status.HTTP_200_OK)
        except (TokenNotFoundError, AlreadyRevokedError):
            return Response(
                {"detail": "This link is no longer valid."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except AlreadyConfirmedError:
            return Response(
                {"detail": "This email change has already been confirmed."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except TokenExpiredError:
            return Response(
                {"detail": "This verification link has expired."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except EmailAlreadyTakenError:
            return Response(
                {
                    "detail": "This email address has been taken by another account."
                },
                status=status.HTTP_409_CONFLICT,
            )

    ####################################################################
    #
    @extend_schema(
        summary="Revoke an email address change ('this wasn't me')",
        description=(
            "Cancel a pending or recently confirmed email change using the "
            "token from the notification sent to the old address.  Valid for "
            "up to 7 days after confirmation.  No authentication required -- "
            "the token is the credential.\n\n"
            "On post-confirmation revocation the email is reverted and all "
            "active sessions are invalidated.\n\n"
            "**Dual-path note:** See ``change_email_confirm`` -- the same "
            "Universal Link / App Link pattern applies here."
        ),
        parameters=[
            OpenApiParameter(
                "token",
                str,
                OpenApiParameter.PATH,
                description="The email-change revocation token.",
            ),
        ],
        request=None,
        responses={200: None},
    )
    @action(
        detail=False,
        methods=["POST"],
        url_path=r"me/change-email/(?P<token>[^/.]+)/revoke",
        permission_classes=[AllowAny],
    )
    def change_email_revoke(self, request, token=None):
        """Revoke an email-change request (old-address token, no auth required)."""
        try:
            revoke_request(token)
            return Response(status=status.HTTP_200_OK)
        except (TokenNotFoundError, AlreadyRevokedError):
            return Response(
                {"detail": "This link is no longer valid."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except RevocationWindowClosedError:
            return Response(
                {
                    "detail": (
                        "The 7-day revocation window for this change has "
                        "closed.  Contact support if you need assistance."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

    ####################################################################
    #
    @extend_schema(
        summary="List current user's outgoing pending invitations",
        description=(
            "Return all pending co-ownership invitations sent by the "
            "authenticated user, across all accounts."
        ),
        responses={200: BankAccountInvitationSerializer(many=True)},
    )
    @action(
        detail=False,
        methods=["GET"],
        url_path="me/invitations",
        permission_classes=[IsAuthenticated, RequiresInteractiveAuth],
    )
    def my_invitations(self, request) -> Response:
        """List outgoing pending co-ownership invitations for the current user."""
        qs = (
            BankAccountInvitation.objects.filter(
                invited_by=request.user,
                status=BankAccountInvitation.Status.PENDING,
            )
            .select_related("bank_account", "bank_account__bank")
            .order_by("-created_at")
        )
        serializer = BankAccountInvitationSerializer(qs, many=True)
        return Response(serializer.data)


########################################################################
########################################################################
#
@extend_schema_view(
    list=extend_schema(
        summary="List the current user's API keys",
        description=(
            "Return all API keys (active, expired, and revoked) belonging "
            "to the authenticated user.  Key material is never included -- "
            "only the displayable prefix."
        ),
    ),
    retrieve=extend_schema(
        summary="Get one of the current user's API keys",
        description="Return a single API key by its UUID.",
    ),
)
class APIKeyViewSet(ListModelMixin, RetrieveModelMixin, GenericViewSet):
    """API keys for the authenticated user.

    Keys are machine credentials that authenticate as their owner but
    are denied access to user/security endpoints -- including this
    viewset: a key cannot be used to mint or revoke keys
    (RequiresInteractiveAuth).
    """

    serializer_class = APIKeySerializer
    queryset = APIKey.objects.all()
    lookup_field = "uuid"
    permission_classes = [IsAuthenticated, RequiresInteractiveAuth]

    ####################################################################
    #
    def get_queryset(self):
        """Restrict to the requesting user's own keys."""
        return APIKey.objects.filter(user=self.request.user)

    ####################################################################
    #
    @extend_schema(
        summary="Create an API key",
        description=(
            "Create a new API key for the authenticated user.  "
            "``expiry_days`` sets the key's lifetime in days (the UI "
            "presets are 30 / 60 / 90 / 365); omit it or pass null for a "
            "key that never expires.\n\n"
            "The response is the **only** time the plaintext ``key`` is "
            "returned; it cannot be recovered afterwards."
        ),
        request=APIKeyCreateSerializer,
        responses={201: APIKeyCreatedSerializer},
    )
    def create(self, request):
        """Create a new API key and return it with the one-time plaintext."""
        serializer = APIKeyCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expiry_days = serializer.validated_data.get("expiry_days")
        expires_at = (
            timezone.now() + timedelta(days=expiry_days)
            if expiry_days is not None
            else None
        )
        api_key, plaintext = APIKey.make(
            user=request.user,
            name=serializer.validated_data["name"],
            expires_at=expires_at,
        )
        # The plaintext is never persisted; it exists only in this
        # response.  APIKeyCreatedSerializer documents the shape for the
        # OpenAPI schema.
        return Response(
            status=status.HTTP_201_CREATED,
            data={**APIKeySerializer(api_key).data, "key": plaintext},
        )

    ####################################################################
    #
    @extend_schema(
        summary="Revoke an API key",
        description=(
            "Permanently revoke an API key.  Revoked keys stop "
            "authenticating immediately but remain listed for audit "
            "purposes.  Revocation cannot be undone."
        ),
        request=None,
        responses={200: APIKeySerializer},
    )
    @action(detail=True, methods=["POST"])
    def revoke(self, request, uuid=None):
        """Revoke one of the current user's API keys."""
        api_key = self.get_object()
        if api_key.is_revoked:
            return Response(
                {"detail": "This API key has already been revoked."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        api_key.revoke()
        return Response(APIKeySerializer(api_key).data)
