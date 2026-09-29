"""
Serializers for funding in the moneypools v1 API.

`FundingEventOccurrenceSerializer` exposes the funding engine's
per-event ledger read by the `/funding-event-occurrences/` endpoints.
`FundingRunResultSerializer`, `FundingSummarySerializer` and
`FundingEventDatesSerializer` describe the response bodies of the
bank-account `run-funding`, `funding-summary` and `funding-event-dates`
actions.
"""

# 3rd party imports
from rest_framework import serializers

# Project imports
from moneypools.models import (
    DECIMAL_PLACES,
    MAX_DIGITS,
    FundingEventOccurrence,
)


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


########################################################################
########################################################################
#
class FundingRunResultSerializer(serializers.Serializer):
    """What one `run-funding` call did."""

    transfers = serializers.IntegerField()
    occurrences_completed = serializers.IntegerField()
    occurrences_partial = serializers.IntegerField()
    warnings = serializers.ListField(child=serializers.CharField())
    skipped_budgets = serializers.ListField(
        child=serializers.CharField(),
        help_text="Names of paused budgets the run skipped.",
    )


########################################################################
########################################################################
#
class FundingScheduleTotalSerializer(serializers.Serializer):
    """The next funding event's total for one funding schedule."""

    schedule = serializers.CharField(help_text="The RRULE string.")
    next_date = serializers.DateField()
    total_amount = serializers.DecimalField(
        max_digits=MAX_DIGITS, decimal_places=DECIMAL_PLACES
    )
    currency = serializers.CharField()
    budget_count = serializers.IntegerField()


########################################################################
########################################################################
#
class FundingSummarySerializer(serializers.Serializer):
    """Per-schedule totals of an account's next funding events."""

    schedules = FundingScheduleTotalSerializer(many=True)
    total_amount = serializers.DecimalField(
        max_digits=MAX_DIGITS, decimal_places=DECIMAL_PLACES
    )
    currency = serializers.CharField()


########################################################################
########################################################################
#
class FundingEventDatesSerializer(serializers.Serializer):
    """Sorted dates on which an account has a funding event due."""

    dates = serializers.ListField(child=serializers.DateField())
