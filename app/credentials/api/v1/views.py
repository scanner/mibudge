"""DRF views for the credentials API (v1)."""

# system imports
from datetime import timedelta

# 3rd party imports
from django.utils import timezone
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

# Project imports
from credentials.models import APIKey
from credentials.permissions import RequiresInteractiveAuth

from .serializers import (
    APIKeyCreatedSerializer,
    APIKeyCreateSerializer,
    APIKeySerializer,
)


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
