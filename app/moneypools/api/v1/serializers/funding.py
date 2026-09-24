"""
Serializer for funding-event occurrences in the moneypools v1 API.

`FundingEventOccurrenceSerializer` exposes the funding engine's
per-event ledger read by the `/funding-event-occurrences/` endpoints.
"""

# 3rd party imports
from rest_framework import serializers

# Project imports
from moneypools.models import FundingEventOccurrence


########################################################################
########################################################################
#
class FundingEventOccurrenceSerializer(serializers.ModelSerializer):
    """Read-only serializer for FundingEventOccurrence rows.

    Exposes the budget UUID as 'budget' rather than the internal pkid so
    callers can cross-reference with the Budget endpoint.
    """

    budget = serializers.UUIDField(source="budget.id", read_only=True)

    class Meta:
        model = FundingEventOccurrence
        fields = [
            "id",
            "budget",
            "kind",
            "scheduled_date",
            "status",
            "completed_at",
            "created_at",
            "modified_at",
        ]
        read_only_fields = fields
