"""
Bank-account co-ownership invitation endpoints for the moneypools v1 API.

`BankAccountInvitationActions` holds the owner-facing actions (send,
list, cancel) and is composed into `BankAccountViewSet`.  The function
views `invitation_detail`, `invitation_accept` and `invitation_decline`
are the public token-based endpoints the invitee uses.
"""

# 3rd party imports
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
)
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

# Project imports
from moneypools.models import BankAccount, BankAccountInvitation
from moneypools.permissions import IsAccountOwner
from moneypools.service import invitation as invitation_svc
from users.permissions import RequiresInteractiveAuth

from ..serializers.invitations import (
    BankAccountInvitationSerializer,
    InviteOwnerSerializer,
    PublicInvitationDetailSerializer,
)


########################################################################
########################################################################
#
class BankAccountInvitationActions(viewsets.GenericViewSet):
    """Co-ownership invitation actions, composed into `BankAccountViewSet`.

    Holds the owner-facing invitation endpoints for a single account:
    `invite`, `invitations` and `invitations/<token>/cancel`.  Each action
    declares its own `permission_classes`, which add
    `RequiresInteractiveAuth` to the viewset's defaults.  Queryset,
    lookup and serializer come from `BankAccountViewSet`.
    """

    ####################################################################
    #
    @extend_schema(
        summary="Invite a co-owner",
        description=(
            "Send a co-ownership invitation to the given email address. "
            "If no mibudge account exists for that address, an inactive "
            "placeholder account is created; the invitee sets their "
            "password after accepting. "
            "Returns 409 if the address is already an owner or a pending "
            "invitation already exists; 429 if too many invitations have "
            "been sent to this address for this account in the rolling "
            "window."
        ),
        request=InviteOwnerSerializer,
        responses={201: None},
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="invite",
        permission_classes=[
            IsAuthenticated,
            IsAccountOwner,
            RequiresInteractiveAuth,
        ],
    )
    def invite(self, request: Request, id: str = "") -> Response:
        """Send a co-ownership invitation email for this bank account."""
        account: BankAccount = self.get_object()
        serializer = InviteOwnerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invitee_email = serializer.validated_data["invitee_email"]
        try:
            invitation_svc.create_invitation(
                account, request.user, invitee_email
            )
        except invitation_svc.InviteeAlreadyOwnerError:
            return Response(
                {
                    "detail": "This address is already a co-owner of the account."
                },
                status=status.HTTP_409_CONFLICT,
            )
        except invitation_svc.InvitationAlreadyPendingError:
            return Response(
                {
                    "detail": "A pending invitation for this address already exists."
                },
                status=status.HTTP_409_CONFLICT,
            )
        except invitation_svc.InvitationWindowExceededError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        return Response(status=status.HTTP_201_CREATED)

    ####################################################################
    #
    @extend_schema(
        summary="List pending invitations for this account",
        description="Returns all pending invitations for this bank account.",
        responses={200: BankAccountInvitationSerializer(many=True)},
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="invitations",
        permission_classes=[
            IsAuthenticated,
            IsAccountOwner,
            RequiresInteractiveAuth,
        ],
    )
    def invitations(self, request: Request, id: str = "") -> Response:
        """List pending co-ownership invitations for this bank account."""
        account: BankAccount = self.get_object()
        qs = (
            BankAccountInvitation.objects.select_related(
                "bank_account", "invited_by"
            )
            .filter(
                bank_account=account,
                status=BankAccountInvitation.Status.PENDING,
            )
            .order_by("-created_at")
        )
        serializer = BankAccountInvitationSerializer(qs, many=True)
        return Response(serializer.data)

    ####################################################################
    #
    @extend_schema(
        summary="Cancel a pending invitation",
        description=(
            "Cancel a pending co-ownership invitation by token. "
            "Only the user who sent the invitation may cancel it."
        ),
        parameters=[
            OpenApiParameter(
                "token",
                str,
                OpenApiParameter.PATH,
                description="The invitation's opaque token.",
            ),
        ],
        request=None,
        responses={200: None},
    )
    @action(
        detail=True,
        methods=["post"],
        url_path=r"invitations/(?P<token>[^/.]+)/cancel",
        permission_classes=[
            IsAuthenticated,
            IsAccountOwner,
            RequiresInteractiveAuth,
        ],
    )
    def cancel_invitation(
        self, request: Request, id: str = "", token: str = ""
    ) -> Response:
        """Cancel a pending co-ownership invitation."""
        self.get_object()  # enforce account ownership check
        try:
            invitation = BankAccountInvitation.objects.get(token=token)
        except BankAccountInvitation.DoesNotExist:
            return Response(
                {"detail": "Invitation not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if invitation.invited_by_id != request.user.pk:
            return Response(
                {"detail": "Only the sender may cancel this invitation."},
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            invitation_svc.cancel_invitation(invitation)
        except invitation_svc.TokenAlreadyCancelledError:
            return Response(
                {"detail": "This invitation has already been cancelled."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except (
            invitation_svc.TokenAlreadyAcceptedError,
            invitation_svc.TokenAlreadyDeclinedError,
        ):
            return Response(
                {"detail": "This invitation can no longer be cancelled."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(status=status.HTTP_200_OK)


########################################################################
########################################################################
# Public invitation endpoints (AllowAny -- token is the credential)
########################################################################
########################################################################
#
@extend_schema(
    summary="Get invitation details (public)",
    description=(
        "Return bank account name, current owners, and invitee status for "
        "the invitation identified by *token*. No authentication required -- "
        "the token is the credential. Used by native apps to render the "
        "acceptance UI; the Django template view renders this server-side."
    ),
    responses={200: PublicInvitationDetailSerializer},
)
@api_view(["GET"])
@permission_classes([AllowAny])
def invitation_detail(request: Request, token: str) -> Response:
    """Return public invitation details by token."""
    try:
        inv = BankAccountInvitation.objects.select_related(
            "bank_account", "bank_account__bank", "invitee_user"
        ).get(token=token)
    except BankAccountInvitation.DoesNotExist:
        return Response(
            {"detail": "Invitation not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    serializer = PublicInvitationDetailSerializer(inv)
    return Response(serializer.data)


########################################################################
########################################################################
#
@extend_schema(
    summary="Accept an invitation (public)",
    description=(
        "Accept the co-ownership invitation identified by *token*. "
        "Adds the invitee to the account's owners. "
        "For brand-new users (no password set), a password-reset email "
        "is also dispatched. No authentication required."
    ),
    request=None,
    responses={
        200: None,
        400: OpenApiResponse(
            description="Invitation expired, cancelled, or already resolved."
        ),
        404: OpenApiResponse(description="Invitation not found."),
    },
)
@api_view(["POST"])
@permission_classes([AllowAny])
def invitation_accept(request: Request, token: str) -> Response:
    """Accept a co-ownership invitation."""
    try:
        invitation_svc.accept_invitation(token, request=request)
        return Response(status=status.HTTP_200_OK)
    except invitation_svc.TokenNotFoundError:
        return Response(
            {"detail": "Invitation not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    except invitation_svc.TokenExpiredError:
        return Response(
            {"detail": "This invitation has expired."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except (
        invitation_svc.TokenAlreadyCancelledError,
        invitation_svc.TokenAlreadyAcceptedError,
        invitation_svc.TokenAlreadyDeclinedError,
    ) as exc:
        match exc:
            case invitation_svc.TokenAlreadyCancelledError():
                detail = "This invitation has been cancelled."
            case invitation_svc.TokenAlreadyAcceptedError():
                detail = "This invitation has already been accepted."
            case _:
                detail = "This invitation has already been declined."
        return Response({"detail": detail}, status=status.HTTP_400_BAD_REQUEST)


########################################################################
########################################################################
#
@extend_schema(
    summary="Decline an invitation (public)",
    description=(
        "Decline the co-ownership invitation identified by *token*. "
        "No authentication required."
    ),
    request=None,
    responses={
        200: None,
        400: OpenApiResponse(
            description="Invitation expired, cancelled, or already resolved."
        ),
        404: OpenApiResponse(description="Invitation not found."),
    },
)
@api_view(["POST"])
@permission_classes([AllowAny])
def invitation_decline(request: Request, token: str) -> Response:
    """Decline a co-ownership invitation."""
    try:
        invitation_svc.decline_invitation(token)
        return Response(status=status.HTTP_200_OK)
    except invitation_svc.TokenNotFoundError:
        return Response(
            {"detail": "Invitation not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    except invitation_svc.TokenExpiredError:
        return Response(
            {"detail": "This invitation has expired."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except (
        invitation_svc.TokenAlreadyCancelledError,
        invitation_svc.TokenAlreadyAcceptedError,
        invitation_svc.TokenAlreadyDeclinedError,
    ) as exc:
        match exc:
            case invitation_svc.TokenAlreadyCancelledError():
                detail = "This invitation has been cancelled."
            case invitation_svc.TokenAlreadyDeclinedError():
                detail = "This invitation has already been declined."
            case _:
                detail = "This invitation has already been accepted."
        return Response({"detail": detail}, status=status.HTTP_400_BAD_REQUEST)
