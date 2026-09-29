"""
Serializers for shared reference data in the moneypools v1 API.

Banks are read-only reference data managed through the admin;
currencies come from `moneyed`.
"""

# 3rd party imports
from rest_framework import serializers

# Project imports
from moneypools.models import Bank


########################################################################
########################################################################
#
class BankSerializer(serializers.ModelSerializer):
    """Read-only serializer for banks.

    Banks are shared reference data managed only through the admin.
    """

    class Meta:
        model = Bank
        fields = [
            "id",
            "name",
            "routing_number",
            "default_currency",
            "created_at",
            "modified_at",
        ]
        read_only_fields = fields


########################################################################
########################################################################
#
class CurrencySerializer(serializers.Serializer):
    """An ISO 4217 currency the system supports."""

    code = serializers.CharField()
    name = serializers.CharField()
    numeric = serializers.CharField(
        allow_null=True,
        help_text="ISO 4217 numeric code; null for historic currencies.",
    )
