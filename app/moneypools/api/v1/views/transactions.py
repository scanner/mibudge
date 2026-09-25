"""
DRF viewsets for transactions and their allocations in the v1 API.

`TransactionViewSet` serves bank transactions plus the `splits` and
`resolve-pending` actions; `TransactionAllocationViewSet` serves the
read-only allocation rows.
"""

# system imports
from decimal import Decimal

# 3rd party imports
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

# Project imports
from common.views import AtomicWritesMixin
from moneypools.models import Transaction, TransactionAllocation
from moneypools.permissions import (
    AccountOwnerCreateMixin,
    AccountOwnerQuerySetMixin,
    IsAccountOwner,
)
from moneypools.service import transaction as transaction_svc

from ..filters import TransactionAllocationFilter, TransactionFilter
from ..serializers.allocations import TransactionAllocationSerializer
from ..serializers.transactions import (
    ResolvePendingSerializer,
    TransactionSerializer,
    TransactionSplitsSerializer,
)


########################################################################
########################################################################
#
@extend_schema_view(
    list=extend_schema(
        summary="List transactions",
        description=(
            "Return transactions belonging to the authenticated user's "
            "accounts. Filterable by bank_account, pending status, "
            "transaction_type, and date range (date_from/date_to). "
            "Searchable by description, raw_description, and party. "
            "Orderable by transaction_date, amount, or created_at."
        ),
    ),
    create=extend_schema(
        summary="Create a transaction",
        description=(
            "Create a new bank transaction. Required: bank_account "
            "(UUID), amount, transaction_date, transaction_type, and "
            "raw_description. A default TransactionAllocation to the "
            "bank account's unallocated budget is auto-created. After "
            "creation, only transaction_type, memo, and description "
            "are updatable."
        ),
    ),
    retrieve=extend_schema(
        summary="Get transaction details",
        description="Return a single transaction by UUID.",
    ),
    update=extend_schema(
        summary="Update a transaction",
        description=(
            "Full update of a transaction. Only transaction_type, "
            "memo, and description are mutable after creation."
        ),
    ),
    partial_update=extend_schema(
        summary="Partially update a transaction",
        description=(
            "Partial update of a transaction. Only transaction_type, "
            "memo, and description are mutable after creation."
        ),
    ),
    destroy=extend_schema(
        summary="Delete a transaction",
        description=(
            "Delete a transaction. Balance changes are reversed by "
            "the pre_delete signal. Associated allocations are "
            "cascade-deleted."
        ),
    ),
)
class TransactionViewSet(
    AtomicWritesMixin,
    AccountOwnerCreateMixin,
    AccountOwnerQuerySetMixin,
    viewsets.ModelViewSet,
):
    """Bank transactions (purchases, deposits, transfers) on user accounts."""

    serializer_class = TransactionSerializer
    queryset = Transaction.objects.select_related("bank_account").all()
    lookup_field = "id"
    permission_classes = [IsAuthenticated, IsAccountOwner]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = TransactionFilter
    search_fields = ["description", "raw_description", "party"]
    ordering_fields = ["transaction_date", "amount", "created_at"]
    ordering = ["-transaction_date", "-created_at"]

    ####################################################################
    #
    def perform_create(self, serializer: TransactionSerializer) -> None:
        """Create a transaction via TransactionService.

        Applies bank-balance math, seeds the default Unallocated
        allocation, and enqueues the cross-account linker.
        """
        data = serializer.validated_data
        tx = transaction_svc.create(
            bank_account=data["bank_account"],
            amount=data["amount"],
            posted_date=data["posted_date"],
            raw_description=data["raw_description"],
            transaction_date=data.get("transaction_date"),
            pending=data.get("pending", False),
            transaction_type=data.get("transaction_type", ""),
            memo=data.get("memo"),
            description=data.get("description", ""),
        )
        serializer.instance = tx

    ####################################################################
    #
    def perform_update(self, serializer: TransactionSerializer) -> None:
        """Update a transaction via TransactionService.

        Routes through the service so that a pending → posted transition
        correctly updates the bank account's posted_balance.

        A user changing `description` sets `description_user_edited`,
        which stops the details-import pipeline from ever recomposing
        the description over the user's text.
        """
        changes = dict(serializer.validated_data)
        instance = serializer.instance
        new_description = changes.get("description")
        if (
            new_description is not None
            and new_description != instance.description
        ):
            changes["description_user_edited"] = True
        transaction_svc.update(instance, **changes)
        serializer.instance.refresh_from_db()

    ####################################################################
    #
    def perform_destroy(self, instance: Transaction) -> None:
        """Delete a transaction via TransactionService.

        Reverses bank and budget balances before deletion.
        """
        transaction_svc.delete(instance)

    ####################################################################
    #
    @extend_schema(
        summary="Declare transaction splits",
        description=(
            "Declaratively set how a transaction's amount is split "
            "across budgets. All referenced budgets must belong to "
            "the same bank account as the transaction. The backend "
            "reconciles existing allocations to match: creating, "
            "updating, or deleting as needed. Any unallocated "
            "remainder gets an allocation to the account's "
            "unallocated budget. Returns all allocations for this "
            "transaction after reconciliation."
        ),
        request=TransactionSplitsSerializer,
        responses={200: TransactionAllocationSerializer(many=True)},
    )
    @action(detail=True, methods=["post"], url_path="splits")
    def splits(self, request: Request, id: str | None = None) -> Response:
        """Reconcile transaction allocations to match declared splits.

        Accepts a dict mapping budget UUIDs to positive amounts.  The
        backend creates, updates, or deletes allocations so that each
        budget listed receives exactly its declared amount.  Any
        remainder (transaction amount minus the sum of splits) is
        assigned to the bank account's unallocated budget.  The
        entire operation runs inside a database transaction.

        Args:
            request: DRF request with body
                ``{"splits": {"<budget-uuid>": "<amount>", ...}}``.
                Amounts are positive decimals; sign is inferred from
                the transaction (negative for debits, positive for
                credits).  An empty dict ``{}`` moves the full amount
                back to the unallocated budget.
            id: UUID of the transaction to split.

        Returns:
            Response containing the full list of
            ``TransactionAllocation`` objects for this transaction
            after reconciliation.
        """
        transaction = self.get_object()

        serializer = TransactionSplitsSerializer(
            data=request.data,
            context={"transaction": transaction},
        )
        serializer.is_valid(raise_exception=True)

        splits: dict[str, Decimal] = serializer.validated_data["splits"]

        try:
            allocations = transaction_svc.split(transaction, splits)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        response_serializer = TransactionAllocationSerializer(
            allocations, many=True
        )
        return Response(response_serializer.data)

    ####################################################################
    #
    @extend_schema(
        summary="Resolve a pending transaction to posted",
        description=(
            "Transition a pending transaction to posted status. "
            "Supplies the bank-confirmed posted date and optionally a "
            "final settled amount (which may differ from the pending "
            "estimate). The bank account's posted_balance is credited; "
            "if the amount changed, available_balance and the "
            "Unallocated allocation are adjusted atomically."
        ),
        request=ResolvePendingSerializer,
        responses={200: TransactionSerializer},
    )
    @action(detail=True, methods=["post"], url_path="resolve-pending")
    def resolve_pending(
        self, request: Request, id: str | None = None
    ) -> Response:
        """Transition a pending transaction to posted.

        Args:
            request: DRF request with body
                ``{"posted_date": "<iso-datetime>", "amount": "<value>"}``.
                ``amount`` is optional; when omitted the original pending
                amount is used as the final settled amount.
            id: UUID of the pending transaction to resolve.

        Returns:
            Response containing the updated Transaction serialized by
            ``TransactionSerializer``.
        """
        transaction = self.get_object()
        if not transaction.pending:
            raise ValidationError("Transaction is not pending.")

        serializer = ResolvePendingSerializer(
            data=request.data,
            context={"transaction": transaction},
        )
        serializer.is_valid(raise_exception=True)

        try:
            updated = transaction_svc.resolve_pending_to_posted(
                transaction,
                new_posted_date=serializer.validated_data["posted_date"],
                new_amount=serializer.validated_data.get("amount"),
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        return Response(TransactionSerializer(updated).data)


########################################################################
########################################################################
#
@extend_schema_view(
    list=extend_schema(
        summary="List transaction allocations",
        description=(
            "Return allocations belonging to the authenticated user's "
            "transactions. Filterable by transaction, budget, and "
            "category. Orderable by created_at."
        ),
    ),
    retrieve=extend_schema(
        summary="Get allocation details",
        description="Return a single transaction allocation by UUID.",
    ),
)
class TransactionAllocationViewSet(
    AtomicWritesMixin,
    AccountOwnerQuerySetMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """Read-only view of budget allocations for transactions.

    All allocation mutations (create, update, delete) must go through the
    transaction ``splits`` action (``POST /api/v1/transactions/<id>/splits/``).
    This ensures ``budget_balance`` snapshots are always recorded correctly
    and that running-balance recalculation on affected budgets is atomic.
    """

    serializer_class = TransactionAllocationSerializer
    queryset = TransactionAllocation.objects.select_related(
        "transaction", "budget"
    ).all()
    lookup_field = "id"
    permission_classes = [IsAuthenticated, IsAccountOwner]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = TransactionAllocationFilter
    ordering_fields = ["created_at"]
    ordering = ["created_at"]
