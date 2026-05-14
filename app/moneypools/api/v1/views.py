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
from datetime import date
from decimal import Decimal

# 3rd party imports
import moneyed
import recurrence as recurrence_lib
from django.utils import timezone
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
from moneypools.service import funding as funding_svc
from moneypools.service import internal_transaction as internal_transaction_svc
from moneypools.service import transaction as transaction_svc
from moneypools.service.shared import funding_system_user

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

    ####################################################################
    #
    @extend_schema(
        summary="Mark import complete",
        description=(
            "Record that a transaction import has been completed for "
            "this account.  Sets last_imported_at to now and advances "
            "last_posted_through to the supplied date (never regresses "
            'an existing value).  Body: {"last_posted_through": "YYYY-MM-DD"}.'
        ),
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "last_posted_through": {"type": "string", "format": "date"}
                },
                "required": ["last_posted_through"],
            }
        },
        responses={200: BankAccountSerializer},
    )
    @action(detail=True, methods=["post"], url_path="mark-imported")
    def mark_imported(self, request: Request, id: str = "") -> Response:
        """Set last_imported_at=now and advance last_posted_through."""
        account: BankAccount = self.get_object()

        raw = request.data.get("last_posted_through")
        if not raw:
            raise ValidationError(
                {"last_posted_through": "This field is required."}
            )
        try:
            posted_through = date.fromisoformat(str(raw))
        except ValueError as exc:
            raise ValidationError(
                {"last_posted_through": "Expected YYYY-MM-DD format."}
            ) from exc

        new_posted_through = (
            max(account.last_posted_through, posted_through)
            if account.last_posted_through is not None
            else posted_through
        )

        BankAccount.objects.filter(pkid=account.pkid).update(
            last_imported_at=timezone.now(),
            last_posted_through=new_posted_through,
        )
        account.refresh_from_db()

        serializer = self.get_serializer(account)
        return Response(serializer.data)

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
                        "deferred": {"type": "boolean"},
                        "transfers": {"type": "integer"},
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
            )
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
        return Response(
            {
                "deferred": report.deferred,
                "transfers": report.transfers,
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
            effective_date=data.get("effective_date"),
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
