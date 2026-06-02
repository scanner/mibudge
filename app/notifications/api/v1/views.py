# 3rd party imports
#
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

# Project imports
#
from notifications.models import (
    Channel,
    ChannelPreference,
    DigestFrequency,
    NotificationPreference,
)
from notifications.registry import registry

from .serializers import (
    ChannelPreferenceSerializer,
    NotificationPreferenceSerializer,
)


########################################################################
########################################################################
#
@extend_schema_view(
    list=extend_schema(
        summary="List notification preferences",
        description=(
            "Return all registered notification kinds merged with the "
            "authenticated user's preferences. Kinds without a stored "
            "preference fall back to the registry default_delivery_mode."
        ),
        responses={200: NotificationPreferenceSerializer(many=True)},
    ),
    partial_update=extend_schema(
        summary="Update a notification preference",
        description=(
            "Set delivery_mode ('digest', 'immediate', or 'off') for a "
            "single notification kind. "
            "Returns 400 if the kind has can_suppress=False. "
            "Returns 404 if the kind is not registered."
        ),
        request=NotificationPreferenceSerializer,
        responses={200: NotificationPreferenceSerializer},
    ),
)
class NotificationPreferenceViewSet(GenericViewSet):
    """Per-user notification kind preferences."""

    permission_classes = [IsAuthenticated]
    serializer_class = NotificationPreferenceSerializer
    lookup_field = "kind"
    # Allow dots in kind strings (e.g. 'users.password_changed').
    lookup_value_regex = r"[^/]+"

    ####################################################################
    #
    def list(self, request):
        """Return all registered kinds with user preference state."""
        user = request.user
        prefs = {
            p.kind: p.delivery_mode
            for p in NotificationPreference.objects.filter(user=user)
        }
        data = [
            {
                "kind": ki.kind,
                "display_name": ki.display_name,
                "can_suppress": ki.can_suppress,
                "delivery_mode": prefs.get(ki.kind, ki.default_delivery_mode),
            }
            for ki in registry.all()
        ]
        serializer = NotificationPreferenceSerializer(data, many=True)
        return Response(serializer.data)

    ####################################################################
    #
    def partial_update(self, request, kind=None):
        """Upsert the user's delivery mode for a single notification kind."""
        kind_info = registry.get(kind)
        if kind_info is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if not kind_info.can_suppress:
            return Response(
                {"detail": "This notification kind cannot be changed."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = NotificationPreferenceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        NotificationPreference.objects.update_or_create(
            user=request.user,
            kind=kind,
            defaults={
                "delivery_mode": serializer.validated_data["delivery_mode"]
            },
        )
        return Response(
            {
                "kind": kind,
                "display_name": kind_info.display_name,
                "can_suppress": kind_info.can_suppress,
                "delivery_mode": serializer.validated_data["delivery_mode"],
            }
        )


########################################################################
########################################################################
#
@extend_schema_view(
    list=extend_schema(
        summary="List channel preferences",
        description=(
            "Return all notification channels with the authenticated "
            "user's delivery preferences. Channels without a stored "
            "preference fall back to DAILY_MORNING."
        ),
        responses={200: ChannelPreferenceSerializer(many=True)},
    ),
    partial_update=extend_schema(
        summary="Update a channel preference",
        description=(
            "Set the digest_frequency for a notification channel. "
            "Returns 404 if the channel value is not valid."
        ),
        request=ChannelPreferenceSerializer,
        responses={200: ChannelPreferenceSerializer},
    ),
)
class ChannelPreferenceViewSet(GenericViewSet):
    """Per-user channel delivery preferences."""

    permission_classes = [IsAuthenticated]
    serializer_class = ChannelPreferenceSerializer
    lookup_field = "channel"

    ####################################################################
    #
    def list(self, request):
        """Return all channels with user preference state."""
        user = request.user
        prefs = {
            p.channel: p.digest_frequency
            for p in ChannelPreference.objects.filter(user=user)
        }
        data = [
            {
                "channel": ch.value,
                "display_name": ch.label,
                "digest_frequency": prefs.get(
                    ch.value, DigestFrequency.DAILY_MORNING
                ),
            }
            for ch in Channel
        ]
        serializer = ChannelPreferenceSerializer(data, many=True)
        return Response(serializer.data)

    ####################################################################
    #
    def partial_update(self, request, channel=None):
        """Upsert the user's preference for a single channel."""
        try:
            ch = Channel(channel)
        except ValueError:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = ChannelPreferenceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ChannelPreference.objects.update_or_create(
            user=request.user,
            channel=channel,
            defaults={
                "digest_frequency": serializer.validated_data[
                    "digest_frequency"
                ]
            },
        )
        return Response(
            {
                "channel": ch.value,
                "display_name": ch.label,
                "digest_frequency": serializer.validated_data[
                    "digest_frequency"
                ],
            }
        )
