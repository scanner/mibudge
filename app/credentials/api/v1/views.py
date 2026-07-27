"""DRF views for the credentials API (v1)."""

# system imports
from datetime import timedelta

# 3rd party imports
from django.utils import timezone
from drf_spectacular.utils import extend_schema, extend_schema_view
from oauth2_provider.generators import generate_client_secret
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet, ModelViewSet

# Project imports
from credentials.models import APIKey, Application
from credentials.permissions import RequiresInteractiveAuth

from .serializers import (
    APIKeyCreatedSerializer,
    APIKeyCreateSerializer,
    APIKeySerializer,
    ApplicationCreatedSerializer,
    ApplicationSerializer,
    ApplicationWriteSerializer,
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


########################################################################
########################################################################
#
@extend_schema_view(
    list=extend_schema(
        summary="List the current user's OAuth2 applications",
        description=(
            "Return the OAuth2 applications registered by the "
            "authenticated user.  Client secrets are never included -- "
            "they are hashed on save and shown only at registration."
        ),
    ),
    retrieve=extend_schema(
        summary="Get one of the current user's OAuth2 applications",
        description="Return a single application by its client ID.",
    ),
    update=extend_schema(
        summary="Replace an OAuth2 application",
        responses={200: ApplicationSerializer},
    ),
    partial_update=extend_schema(
        summary="Update an OAuth2 application",
        description=(
            "Update the application's name or redirect URIs.  "
            "``client_type`` cannot be changed after registration."
        ),
        responses={200: ApplicationSerializer},
    ),
    destroy=extend_schema(
        summary="Deregister an OAuth2 application",
        description=(
            "Delete the application.  Every grant, access token and "
            "refresh token issued for it is deleted with it, so any "
            "user who authorized this app loses access immediately."
        ),
    ),
)
class ApplicationViewSet(ModelViewSet):
    """OAuth2 applications registered by the authenticated user.

    Registration is deliberately narrow: the caller chooses a name, a
    client type and redirect URIs, and everything that constitutes
    policy -- grant type, visibility, lifecycle status, consent
    skipping -- is set here or by staff.  See ApplicationWriteSerializer
    for why each withheld field is withheld.

    Scoped to the requesting user's own applications.  Registering an
    app is not the same as authorizing one: a user's grants against
    *other* people's apps are managed separately.
    """

    queryset = Application.objects.all()
    lookup_field = "client_id"
    permission_classes = [IsAuthenticated, RequiresInteractiveAuth]

    ####################################################################
    #
    def get_queryset(self):
        """Restrict to applications the requesting user registered."""
        return Application.objects.filter(user=self.request.user).order_by(
            "-created"
        )

    ####################################################################
    #
    def get_serializer_class(self):
        """Use the write serializer for mutating actions."""
        if self.action in ("create", "update", "partial_update"):
            return ApplicationWriteSerializer
        return ApplicationSerializer

    ####################################################################
    #
    def update(self, request, *args, **kwargs):
        """Update an application, echoing back the full read representation.

        DRF's default update() serializes the response with the same
        (write) serializer it validated the request with.  That would
        return only the writable fields and, worse, render redirect_uris
        by iterating the model's space-separated string character by
        character.  Re-serialize with ApplicationSerializer instead, so
        the response matches list/retrieve -- mirroring create(), which
        does the same for the same reason.
        """
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(
            instance, data=request.data, partial=partial
        )
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(ApplicationSerializer(instance).data)

    ####################################################################
    #
    @extend_schema(
        summary="Register an OAuth2 application",
        description=(
            "Register a new OAuth2 application owned by the "
            "authenticated user.  The application uses the "
            "authorization-code grant with PKCE; no other grant type is "
            "offered.\n\n"
            "New applications start private to their owner and in the "
            "``testing`` lifecycle stage; only staff can promote an "
            "application to global or publish it.\n\n"
            "For ``confidential`` clients the response is the **only** "
            "time ``client_secret`` is returned -- it is hashed on save "
            "and cannot be recovered.  ``public`` clients get null: they "
            "cannot keep a secret and authenticate with PKCE instead."
        ),
        request=ApplicationWriteSerializer,
        responses={201: ApplicationCreatedSerializer},
    )
    def create(self, request, *args, **kwargs):
        """Register an application, returning the secret exactly once."""
        serializer = ApplicationWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        confidential = (
            serializer.validated_data["client_type"]
            == Application.CLIENT_CONFIDENTIAL
        )
        # Generate the secret here rather than letting the model default
        # do it: ClientSecretField hashes on save, so this is the only
        # moment the plaintext exists to hand back.
        plaintext_secret = generate_client_secret() if confidential else None

        application = serializer.save(
            user=request.user,
            # The per-app half of the grant-type policy; see
            # OAUTH2_PROVIDER in settings for the other two halves.
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            **({"client_secret": plaintext_secret} if confidential else {}),
        )

        return Response(
            status=status.HTTP_201_CREATED,
            data={
                **ApplicationSerializer(application).data,
                "client_secret": plaintext_secret,
            },
        )
