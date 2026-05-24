from allauth.account.internal.flows.password_change import (
    change_password as allauth_change_password,
)
from allauth.account.signals import password_changed
from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.mixins import (
    ListModelMixin,
    RetrieveModelMixin,
    UpdateModelMixin,
)
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from .serializers import ChangePasswordSerializer, UserSerializer

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
    permission_classes = [IsAdminUser]
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
            "Available to any authenticated user (not restricted to staff)."
        ),
    )
    @action(
        detail=False,
        methods=["GET", "PATCH"],
        permission_classes=[IsAuthenticated],
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
        permission_classes=[IsAuthenticated],
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
