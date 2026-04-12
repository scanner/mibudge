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

# 3rd party imports
import moneyed
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import (
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework import mixins, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
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
    def perform_create(self, serializer: BankAccountSerializer) -> None:
        """Save the new bank account and add the requesting user as owner."""
        bank_account = serializer.save()
        bank_account.owners.add(self.request.user)


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
            "Delete a budget. The unallocated budget cannot be "
            "deleted -- returns 403."
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
    def perform_destroy(self, instance: Budget) -> None:
        """Prevent deletion of the unallocated budget."""
        bank_account = instance.bank_account
        if bank_account.unallocated_budget_id == instance.id:
            raise PermissionDenied("Cannot delete the unallocated budget.")
        instance.delete()


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
    ordering = ["-transaction_date"]

    ####################################################################
    #
    def perform_create(self, serializer: TransactionSerializer) -> None:
        """Save the transaction and create a default allocation.

        The default allocation assigns the full transaction amount to
        the bank account's unallocated budget.
        """
        transaction = serializer.save()
        TransactionAllocation.objects.create(
            transaction=transaction,
            budget=transaction.bank_account.unallocated_budget,
            amount=transaction.amount,
        )


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
    create=extend_schema(
        summary="Create a transaction allocation",
        description=(
            "Allocate a portion of a transaction's amount to a "
            "budget. Required: transaction (UUID) and amount. "
            "Optional: budget (UUID, defaults to unallocated) and "
            "category. The total allocated across all allocations "
            "for a transaction must not exceed the transaction amount."
        ),
    ),
    retrieve=extend_schema(
        summary="Get allocation details",
        description="Return a single transaction allocation by UUID.",
    ),
    update=extend_schema(
        summary="Update an allocation",
        description=(
            "Full update of an allocation. After creation, budget, "
            "category, and memo are updatable. Amount and transaction "
            "are immutable."
        ),
    ),
    partial_update=extend_schema(
        summary="Partially update an allocation",
        description=(
            "Partial update of an allocation. After creation, budget, "
            "category, and memo are updatable."
        ),
    ),
    destroy=extend_schema(
        summary="Delete an allocation",
        description=(
            "Delete a transaction allocation. Budget balance changes "
            "are reversed by the pre_delete signal."
        ),
    ),
)
class TransactionAllocationViewSet(
    AccountOwnerQuerySetMixin, viewsets.ModelViewSet
):
    """Budget allocations for transactions (supports split transactions)."""

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
        serializer.save(actor=self.request.user)


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
