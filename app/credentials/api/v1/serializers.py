"""DRF serializers for the credentials API (v1)."""

# 3rd party imports
from rest_framework import serializers

# Project imports
from credentials.models import APIKey


########################################################################
########################################################################
#
class APIKeySerializer(serializers.ModelSerializer):
    """Read serializer for API keys.

    Never exposes the key material -- only the displayable prefix.  The
    plaintext key appears exactly once, in the creation response (see
    APIKeyViewSet.create).
    """

    class Meta:
        model = APIKey
        fields = [
            "uuid",
            "name",
            "prefix",
            "expires_at",
            "last_used_at",
            "revoked_at",
            "created_at",
        ]
        read_only_fields = fields


########################################################################
########################################################################
#
class APIKeyCreateSerializer(serializers.Serializer):
    """Validate an API-key creation request.

    ``expiry_days`` covers all the expiry presets (30 / 60 / 90 / 365 /
    a specific number of days); null or omitted means the key never
    expires.  The presets themselves are a UI concern.
    """

    name = serializers.CharField(max_length=100)
    expiry_days = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        max_value=3650,
    )


########################################################################
########################################################################
#
class APIKeyCreatedSerializer(APIKeySerializer):
    """Creation response -- the only place the plaintext key appears.

    Exists to document the creation response shape in the OpenAPI
    schema; the view assembles the payload itself.  ``key`` is never a
    model field and cannot be recovered after this response.
    """

    key = serializers.CharField(read_only=True)

    class Meta(APIKeySerializer.Meta):
        fields = [*APIKeySerializer.Meta.fields, "key"]
        read_only_fields = fields
