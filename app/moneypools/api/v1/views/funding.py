"""
Funding endpoints for the moneypools v1 API.

`BankAccountFundingActions` holds the per-account funding-engine
actions and is composed into `BankAccountViewSet`.
`FundingEventOccurrenceViewSet` serves the read-only funding-event
ledger.
"""

# system imports
from datetime import date
from decimal import Decimal

# 3rd party imports
import recurrence as recurrence_lib
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import (
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

# Project imports
from moneypools.models import BankAccount, Budget, FundingEventOccurrence
from moneypools.permissions import IsAccountOwner
from moneypools.service import funding as funding_svc
from moneypools.service.shared import funding_system_user

from ..filters import FundingEventOccurrenceFilter
from ..serializers.funding import FundingEventOccurrenceSerializer


########################################################################
########################################################################
#
class BankAccountFundingActions(viewsets.GenericViewSet):
    """Bank-account funding actions, composed into `BankAccountViewSet`.

    Holds the endpoints that run or preview the funding engine for a
    single account: `run-funding`, `funding-event-dates` and
    `funding-summary`.  Queryset, lookup, serializer and permissions
    come from `BankAccountViewSet`.
    """

    ####################################################################
    #
    @extend_schema(
        summary="Run funding",
        description=(
            "Run the funding engine for this account immediately.  "
            "Processes all due fund and recurrence events up to `as_of` "
            "(defaults to today) and returns a summary of what happened.  "
            "Pass `as_of` when calling between import batches so the engine "
            "only sees events up to that batch boundary date."
        ),
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "as_of": {
                        "type": "string",
                        "format": "date",
                        "description": (
                            "Upper bound for event enumeration (YYYY-MM-DD). "
                            "Defaults to today."
                        ),
                    }
                },
            }
        },
        responses={
            200: OpenApiResponse(
                description="Funding run result.",
                response={
                    "type": "object",
                    "properties": {
                        "transfers": {"type": "integer"},
                        "occurrences_completed": {"type": "integer"},
                        "occurrences_partial": {"type": "integer"},
                        "warnings": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "skipped_budgets": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                },
            ),
            409: OpenApiResponse(
                description=(
                    "Either another worker is currently processing this "
                    "account (lock held), or there is nothing due or "
                    "outstanding to run as of the supplied date."
                ),
            ),
        },
    )
    @action(detail=True, methods=["post"], url_path="run-funding")
    def run_funding(self, request: Request, id: str = "") -> Response:
        """Run the funding engine for this account and return a summary."""
        account: BankAccount = self.get_object()

        as_of_raw = request.data.get("as_of")
        if as_of_raw is not None:
            try:
                as_of = date.fromisoformat(str(as_of_raw))
            except ValueError as exc:
                raise ValidationError(
                    {"as_of": "Must be a date in YYYY-MM-DD format."}
                ) from exc
        else:
            as_of = date.today()

        try:
            system_user = funding_system_user()
        except Exception:
            return Response(
                {"detail": "Funding system user not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        report = funding_svc.fund_account(account, as_of, system_user)

        # Another worker is already running funding for this account;
        # refuse rather than wait, so the user gets immediate feedback
        # and we do not duplicate transfers.
        #
        if report.busy:
            return Response(
                {
                    "detail": (
                        "Funding is already running for this account; "
                        "try again in a moment."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )

        # Nothing material happened -- no transfers, no occurrences
        # transitioned, no paused-skips.  This is the spam-click path
        # after a complete run; surface it as a 409 so the UI can show
        # an idempotent "nothing to do" state instead of a misleading
        # success.
        #
        nothing_to_do = (
            report.transfers == 0
            and report.occurrences_completed == 0
            and report.occurrences_partial == 0
            and not report.skipped_budgets
        )
        if nothing_to_do:
            return Response(
                {
                    "detail": (
                        "No funding events are due or outstanding for "
                        "this account as of the requested date."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )

        return Response(
            {
                "transfers": report.transfers,
                "occurrences_completed": report.occurrences_completed,
                "occurrences_partial": report.occurrences_partial,
                "warnings": report.warnings,
                "skipped_budgets": report.skipped_budgets,
            }
        )

    ####################################################################
    #
    @extend_schema(
        summary="Funding event dates",
        description=(
            "Return all dates in (after, before] on which at least one "
            "funding or recurrence event is due for this account.  "
            "The importer uses this to find batch-split boundaries."
        ),
        responses={
            200: OpenApiResponse(
                description="Sorted list of event dates.",
                response={
                    "type": "object",
                    "properties": {
                        "dates": {
                            "type": "array",
                            "items": {"type": "string", "format": "date"},
                        }
                    },
                },
            )
        },
    )
    @action(detail=True, methods=["get"], url_path="funding-event-dates")
    def funding_event_dates(self, request: Request, id: str = "") -> Response:
        """Return funding event dates in a query-param date range."""
        account: BankAccount = self.get_object()

        after_raw = request.query_params.get("after")
        before_raw = request.query_params.get("before")

        if not after_raw or not before_raw:
            raise ValidationError(
                {
                    "detail": "Both 'after' and 'before' query params are required."
                }
            )
        try:
            after = date.fromisoformat(after_raw)
            before = date.fromisoformat(before_raw)
        except ValueError as exc:
            raise ValidationError(
                {"detail": "Dates must be in YYYY-MM-DD format."}
            ) from exc

        dates = funding_svc.funding_event_dates(account, after, before)
        return Response({"dates": [d.isoformat() for d in dates]})

    ####################################################################
    #
    @extend_schema(
        summary="Funding summary",
        description=(
            "Return the total amounts that will be automatically funded "
            "at the next event for each distinct funding schedule on this "
            "account.  Only active, schedulable budgets are included -- "
            "paused, archived, completed goals, and RECURRING budgets "
            "that delegate to a fill-up goal are excluded.  Results are "
            "grouped by funding schedule (RRULE string) and sorted by "
            "next event date."
        ),
        responses={
            200: OpenApiResponse(
                description="Per-schedule funding totals.",
                response={
                    "type": "object",
                    "properties": {
                        "schedules": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "schedule": {"type": "string"},
                                    "next_date": {
                                        "type": "string",
                                        "format": "date",
                                    },
                                    "total_amount": {"type": "string"},
                                    "currency": {"type": "string"},
                                    "budget_count": {"type": "integer"},
                                },
                            },
                        },
                        "total_amount": {"type": "string"},
                        "currency": {"type": "string"},
                    },
                },
            )
        },
    )
    @action(detail=True, methods=["get"], url_path="funding-summary")
    def funding_summary(self, request: Request, id: str = "") -> Response:
        """Aggregate next-event funding amounts across all budgets."""
        account: BankAccount = self.get_object()
        today = date.today()

        budgets = list(Budget.objects.filter(bank_account=account))

        # Map ASSOCIATED_FILLUP_GOAL budget UUID -> parent RECURRING budget,
        # so we can group fill-up goals under the parent's schedule.
        fillup_to_parent: dict[object, Budget] = {}
        for b in budgets:
            if b.fillup_goal_id is not None:
                fillup_to_parent[b.fillup_goal_id] = b

        groups: dict[str, dict] = {}
        grand_total = Decimal("0")
        currency = account.currency

        for budget in budgets:
            info = funding_svc.next_funding_info(budget, today=today)
            if info is None:
                continue

            if budget.budget_type == Budget.BudgetType.ASSOCIATED_FILLUP_GOAL:
                parent = fillup_to_parent.get(budget.id)
                if parent is None:
                    continue
                sched_key = recurrence_lib.serialize(parent.funding_schedule)
            else:
                sched_key = recurrence_lib.serialize(budget.funding_schedule)

            amount = info.amount.amount
            currency = str(info.amount.currency)

            if sched_key not in groups:
                groups[sched_key] = {
                    "schedule": sched_key,
                    "next_date": info.date,
                    "total_amount": Decimal("0"),
                    "currency": currency,
                    "budget_count": 0,
                }

            g = groups[sched_key]
            g["next_date"] = min(g["next_date"], info.date)
            g["total_amount"] += amount
            g["budget_count"] += 1
            grand_total += amount

        schedules = sorted(groups.values(), key=lambda g: g["next_date"])
        for g in schedules:
            g["total_amount"] = str(g["total_amount"])
            g["next_date"] = g["next_date"].isoformat()

        return Response(
            {
                "schedules": schedules,
                "total_amount": str(grand_total),
                "currency": currency,
            }
        )


########################################################################
########################################################################
#
@extend_schema_view(
    list=extend_schema(
        summary="List funding event occurrences",
        description=(
            "Return funding event occurrences for budgets on accounts "
            "owned by the authenticated user.  Filterable by bank_account, "
            "budget, kind, status (multi-value), and scheduled_date range.  "
            "Orderable by scheduled_date or created_at."
        ),
    ),
    retrieve=extend_schema(
        summary="Get a funding event occurrence",
        description="Return a single funding event occurrence by UUID.",
    ),
)
class FundingEventOccurrenceViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only access to FundingEventOccurrence rows for owned accounts."""

    serializer_class = FundingEventOccurrenceSerializer
    queryset = FundingEventOccurrence.objects.select_related(
        "budget__bank_account"
    ).all()
    lookup_field = "id"
    permission_classes = [IsAuthenticated, IsAccountOwner]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = FundingEventOccurrenceFilter
    ordering_fields = ["scheduled_date", "created_at"]
    ordering = ["-scheduled_date"]

    ####################################################################
    #
    def get_queryset(self):
        """Restrict to occurrences on accounts the requesting user owns."""
        return FundingEventOccurrence.objects.select_related(
            "budget__bank_account"
        ).filter(budget__bank_account__owners=self.request.user)
