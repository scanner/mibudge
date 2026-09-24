"""
DRF viewset for budgets (virtual envelopes) in the moneypools v1 API.
"""

# 3rd party imports
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

# Project imports
from moneypools.models import Budget
from moneypools.permissions import (
    AccountOwnerCreateMixin,
    AccountOwnerQuerySetMixin,
    IsAccountOwner,
)
from moneypools.service import budget as budget_svc

from ..filters import BudgetFilter
from ..serializers.budgets import BudgetSerializer


########################################################################
########################################################################
#
@extend_schema_view(
    list=extend_schema(
        summary="List budgets",
        description=(
            "Return budgets belonging to the authenticated user's "
            "accounts. Filterable by bank_account, budget_type, "
            "archived, and paused. Searchable by name. Orderable by "
            "name, created_at, or balance."
        ),
    ),
    create=extend_schema(
        summary="Create a budget",
        description=(
            "Create a new budget under a bank account. Required: "
            "name, bank_account (UUID), budget_type, funding_type, "
            "and target_balance. The bank_account and budget_type are "
            "immutable after creation. Balance is managed by signals "
            "and is always read-only."
        ),
    ),
    retrieve=extend_schema(
        summary="Get budget details",
        description="Return a single budget by UUID.",
    ),
    update=extend_schema(
        summary="Update a budget",
        description=(
            "Full update of a budget. bank_account and budget_type "
            "are immutable. The unallocated budget cannot be renamed."
        ),
    ),
    partial_update=extend_schema(
        summary="Partially update a budget",
        description=(
            "Partial update of a budget. bank_account and budget_type "
            "are immutable. The unallocated budget cannot be renamed."
        ),
    ),
    destroy=extend_schema(
        summary="Delete a budget",
        description=(
            "Delete a budget. The unallocated budget cannot be deleted "
            "(403). A budget with existing transaction allocations cannot "
            "be deleted (400) -- archive it instead."
        ),
    ),
)
class BudgetViewSet(
    AccountOwnerCreateMixin, AccountOwnerQuerySetMixin, viewsets.ModelViewSet
):
    """Virtual sub-accounts (goals, recurring budgets) within a bank account."""

    serializer_class = BudgetSerializer
    queryset = Budget.objects.select_related(
        "bank_account", "fillup_goal"
    ).all()
    lookup_field = "id"
    permission_classes = [IsAuthenticated, IsAccountOwner]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = BudgetFilter
    search_fields = ["name"]
    ordering_fields = ["name", "created_at", "balance"]
    ordering = ["name"]

    ####################################################################
    #
    def perform_create(self, serializer: BudgetSerializer) -> None:
        """Create a budget via the service layer so fill-up goal is created.

        Raises:
            ValidationError: On service-layer errors.
        """
        validated = serializer.validated_data
        bank_account = validated.pop("bank_account")
        name = validated.pop("name")
        # `budget_type` and `funding_type` are optional in the serializer
        # because the model fields have defaults, and DRF leaves omitted
        # optional fields out of `validated_data`.  Fall back to the
        # model defaults (Goal, Target Date) so an omitted field creates
        # the documented default budget instead of raising `KeyError`.
        #
        budget_type = validated.pop("budget_type", Budget.BudgetType.GOAL)
        funding_type = validated.pop(
            "funding_type", Budget.FundingType.TARGET_DATE
        )
        target_balance = validated.pop("target_balance")
        budget = budget_svc.create(
            bank_account=bank_account,
            name=name,
            budget_type=budget_type,
            funding_type=funding_type,
            target_balance=target_balance,
            **validated,
        )
        serializer.instance = budget

    ####################################################################
    #
    def update(
        self, request: Request, *args: object, **kwargs: object
    ) -> Response:
        """Update a budget and return the result with any unpause warnings.

        Overrides the default DRF update so that warnings emitted by the
        service layer (e.g. missed recur boundaries on unpause) are
        included in the response payload alongside the serialized budget.

        Args:
            request: The incoming HTTP request.
            *args: Positional arguments forwarded from the router.
            **kwargs: Keyword arguments forwarded from the router (may
                include 'partial' for PATCH requests).
        """
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(
            instance, data=request.data, partial=partial
        )
        serializer.is_valid(raise_exception=True)
        _, warnings = budget_svc.update(instance, **serializer.validated_data)
        instance.refresh_from_db()
        serializer.instance = instance
        return Response({**serializer.data, "warnings": warnings})

    ####################################################################
    #
    def perform_destroy(self, instance: Budget) -> None:
        """Delete a budget via BudgetService.

        Raises:
            PermissionDenied: If the budget is the account's unallocated budget.
            ValidationError: If the budget has existing transaction allocations;
                the caller should archive the budget instead.
        """
        try:
            budget_svc.delete(instance, actor=self.request.user)
        except ValueError as exc:
            msg = str(exc)
            if "unallocated" in msg:
                raise PermissionDenied(msg) from exc
            raise ValidationError(msg) from exc

    ####################################################################
    #
    @extend_schema(
        summary="Archive a budget",
        description=(
            "Archive a budget. Any remaining balance is transferred to the "
            "account's unallocated budget. If the budget has an associated "
            "fill-up goal, that budget is also archived and its balance moved "
            "to unallocated. The unallocated budget cannot be archived."
        ),
        responses={200: BudgetSerializer},
    )
    @action(detail=True, methods=["post"], url_path="archive")
    def archive(self, request: Request, id: str | None = None) -> Response:
        """Archive a budget and move its funds to unallocated."""
        budget = self.get_object()
        try:
            budget = budget_svc.archive(budget, actor=request.user)
        except ValueError as exc:
            msg = str(exc)
            if "unallocated" in msg:
                raise PermissionDenied(msg) from exc
            raise ValidationError(msg) from exc
        return Response(
            self.get_serializer(budget).data, status=status.HTTP_200_OK
        )
