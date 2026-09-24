"""
Serializers for shared reference data in the moneypools v1 API.

Banks are read-only reference data managed through the admin.
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
