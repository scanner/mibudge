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

from .serializers import UserSerializer

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
