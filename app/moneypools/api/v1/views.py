"""
DRF viewsets for the moneypools domain.

All viewsets use UUID-based lookup (``id`` field) and require JWT
authentication.  Object-level access is enforced by
``AccountOwnerQuerySetMixin`` (filters list queries to owned objects)
and ``IsAccountOwner`` (guards retrieve/update/delete on individual
objects).

Banks are read-only reference data.  All other resources support the
standard CRUD operations with restrictions documented per-viewset.
"""

# system imports
from decimal import Decimal

# 3rd party imports
import moneyed
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import (
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

# Project imports
from moneypools.models import (
    Bank,
    BankAccount,
    Budget,
    InternalTransaction,
    Transaction,
    TransactionAllocation,
)
from moneypools.permissions import AccountOwnerQuerySetMixin, IsAccountOwner
from moneypools.service import bank_account as bank_account_svc
from moneypools.service import budget as budget_svc
from moneypools.service import internal_transaction as internal_transaction_svc
from moneypools.service import transaction as transaction_svc

from .filters import (
    BudgetFilter,
    InternalTransactionFilter,
    TransactionAllocationFilter,
    TransactionFilter,
)
from .serializers import (
    BankAccountSerializer,
    BankSerializer,
    BudgetSerializer,
    InternalTransactionSerializer,
    TransactionAllocationSerializer,
    TransactionSerializer,
    TransactionSplitsSerializer,
)


########################################################################
########################################################################
#
@extend_schema_view(
    list=extend_schema(
        summary="List banks",
        description=(
            "Return all banks in the system. Banks are shared reference "
            "data managed through the admin -- any authenticated user "
            "can list and retrieve them."
        ),
    ),
    retrieve=extend_schema(
        summary="Get bank details",
        description="Return a single bank by UUID.",
    ),
)
class BankViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only reference data for financial institutions."""

    serializer_class = BankSerializer
    queryset = Bank.objects.all()
    lookup_field = "id"
    permission_classes = [IsAuthenticated]
    filter_backends = [OrderingFilter]
    ordering_fields = ["name"]
    ordering = ["name"]


########################################################################
########################################################################
#
@extend_schema_view(
    list=extend_schema(
        summary="List bank accounts",
        description=(
            "Return bank accounts owned by the authenticated user. "
            "Filterable by account_type. Orderable by name or "
            "created_at."
        ),
    ),
    create=extend_schema(
        summary="Create a bank account",
        description=(
            "Create a new bank account. The authenticated user is "
            "automatically added as an owner. An 'Unallocated' budget "
            "is auto-created by a post_save signal. Optionally set "
            "initial posted_balance, available_balance, and currency "
            "(all immutable after creation)."
        ),
    ),
    retrieve=extend_schema(
        summary="Get bank account details",
        description="Return a single bank account by UUID.",
    ),
    update=extend_schema(
        summary="Update a bank account",
        description=(
            "Full update of a bank account. Only 'name' is mutable "
            "after creation -- bank, account_type, currency, and "
            "balances are rejected if changed."
        ),
    ),
    partial_update=extend_schema(
        summary="Partially update a bank account",
        description=(
            "Partial update of a bank account. Only 'name' is mutable "
            "after creation."
        ),
    ),
    destroy=extend_schema(
        summary="Delete a bank account",
        description=(
            "Delete a bank account and all associated budgets, "
            "transactions, and allocations."
        ),
    ),
)
class BankAccountViewSet(AccountOwnerQuerySetMixin, viewsets.ModelViewSet):
    """Bank accounts (checking, savings, credit card) owned by the user."""

    serializer_class = BankAccountSerializer
    queryset = BankAccount.objects.select_related(
        "bank", "unallocated_budget"
    ).all()
    lookup_field = "id"
    permission_classes = [IsAuthenticated, IsAccountOwner]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["account_type"]
    ordering_fields = ["name", "created_at"]
    ordering = ["name"]

    ####################################################################
    #
    def perform_update(self, serializer: BankAccountSerializer) -> None:
        """Update a bank account via BankAccountService (acquires lock)."""
        bank_account_svc.update(
            serializer.instance, **serializer.validated_data
        )
        serializer.instance.refresh_from_db()

    ####################################################################
    #
    def perform_create(self, serializer: BankAccountSerializer) -> None:
        """Create a bank account via BankAccountService."""
        data = serializer.validated_data
        optional = {
            k: data[k]
            for k in (
                "account_number",
                "currency",
                "posted_balance",
                "available_balance",
            )
            if k in data
        }
        account = bank_account_svc.create(
            bank=data["bank"],
            name=data["name"],
            account_type=data["account_type"],
            owners=[self.request.user],
            **optional,
        )
        serializer.instance = account


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
class BudgetViewSet(AccountOwnerQuerySetMixin, viewsets.ModelViewSet):
    """Virtual sub-accounts (goals, recurring budgets) within a bank account."""

    serializer_class = BudgetSerializer
    queryset = Budget.objects.select_related("bank_account").all()
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
        budget_type = validated.pop("budget_type")
        funding_type = validated.pop("funding_type")
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
    def perform_update(self, serializer: BudgetSerializer) -> None:
        """Update a budget via the service layer so fill-up goal is created.

        Raises:
            ValidationError: On service-layer errors.
        """
        budget_svc.update(serializer.instance, **serializer.validated_data)
        serializer.instance.refresh_from_db()

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
class TransactionViewSet(AccountOwnerQuerySetMixin, viewsets.ModelViewSet):
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
        """
        transaction_svc.update(serializer.instance, **serializer.validated_data)
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


########################################################################
########################################################################
#
@extend_schema_view(
    list=extend_schema(
        summary="List internal transactions",
        description=(
            "Return budget-to-budget transfers belonging to the "
            "authenticated user's accounts. Filterable by "
            "bank_account, src_budget, dst_budget, and date range "
            "(date_from/date_to). Orderable by created_at."
        ),
    ),
    create=extend_schema(
        summary="Create an internal transaction",
        description=(
            "Transfer money between two budgets in the same bank "
            "account. Required: bank_account (UUID), amount, "
            "src_budget (UUID), and dst_budget (UUID). The "
            "authenticated user is recorded as the actor. Internal "
            "transactions are write-once -- to reverse a transfer, "
            "create a new one with src and dst swapped."
        ),
    ),
    retrieve=extend_schema(
        summary="Get internal transaction details",
        description="Return a single internal transaction by UUID.",
    ),
)
class InternalTransactionViewSet(
    AccountOwnerQuerySetMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """Write-once budget-to-budget transfers within a bank account."""

    serializer_class = InternalTransactionSerializer
    queryset = InternalTransaction.objects.select_related(
        "bank_account", "src_budget", "dst_budget", "actor"
    ).all()
    lookup_field = "id"
    permission_classes = [IsAuthenticated, IsAccountOwner]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = InternalTransactionFilter
    ordering_fields = ["created_at"]
    ordering = ["-created_at"]

    ####################################################################
    #
    def perform_create(self, serializer: InternalTransactionSerializer) -> None:
        """Save the internal transaction with the requesting user as actor."""
        data = serializer.validated_data
        serializer.instance = internal_transaction_svc.create(
            bank_account=data["bank_account"],
            src_budget=data["src_budget"],
            dst_budget=data["dst_budget"],
            amount=data["amount"],
            actor=self.request.user,
        )


########################################################################
########################################################################
#
@extend_schema(
    summary="List supported currencies",
    description=(
        "Return all ISO 4217 currency codes supported by the system, "
        "sorted by code. Each entry includes the code, English name, "
        "and numeric ISO 4217 code. Requires authentication."
    ),
    responses={
        200: OpenApiResponse(
            description="List of supported currencies.",
        ),
    },
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def currencies(request: Request) -> Response:
    """Return all supported ISO 4217 currencies, sorted by code."""
    data = [
        {"code": c.code, "name": c.name, "numeric": c.numeric}
        for c in sorted(moneyed.CURRENCIES.values(), key=lambda c: c.code)
    ]
    return Response(data)
