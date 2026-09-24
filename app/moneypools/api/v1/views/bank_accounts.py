"""
DRF viewset for bank accounts in the moneypools v1 API.

`BankAccountViewSet` owns the CRUD endpoints at `/bank-accounts/` and
the class attributes (queryset, serializer, lookup, permissions,
filters) every bank-account action runs with.  Its `@action` endpoints
live in mixins composed into the class; DRF's `get_extra_actions()`
walks the MRO, so they route at `/bank-accounts/<id>/<url_path>/`:

- `BankAccountImportActions` (`views/imports.py`): `mark-imported`,
  `sync-scrape`, `transaction-details`.
- `BankAccountFundingActions` (`views/funding.py`): `run-funding`,
  `funding-event-dates`, `funding-summary`.
- `BankAccountInvitationActions` (`views/invitations.py`): `invite`,
  `invitations`, `invitations/<token>/cancel`.
"""

# 3rd party imports
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import IsAuthenticated

# Project imports
from moneypools.models import BankAccount
from moneypools.permissions import (
    AccountOwnerCreateMixin,
    AccountOwnerQuerySetMixin,
    IsAccountOwner,
)
from moneypools.service import bank_account as bank_account_svc

from ..serializers.bank_accounts import BankAccountSerializer
from .funding import BankAccountFundingActions
from .imports import BankAccountImportActions
from .invitations import BankAccountInvitationActions


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
class BankAccountViewSet(
    AccountOwnerCreateMixin,
    AccountOwnerQuerySetMixin,
    BankAccountImportActions,
    BankAccountFundingActions,
    BankAccountInvitationActions,
    viewsets.ModelViewSet,
):
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
