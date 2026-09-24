"""
DRF permissions for the moneypools domain.

All permissions are at the BankAccount level. A user who is in a bank
account's 'owners' M2M has full access to the account and all its
related objects (budgets, transactions, allocations, internal
transactions).

Banks are shared reference data and require only authentication.

Ownership is enforced in three layers:

- Reads, updates and deletes: `AccountOwnerQuerySetMixin` scopes the
  queryset, so `get_object()` returns 404 for unowned objects, and
  `IsAccountOwner.has_object_permission` re-checks the fetched object.
- Create: DRF never calls object-level permissions on create, so
  writable `bank_account` fields use `OwnedBankAccountField`
  (`moneypools/api/v1/fields.py`), which resolves the UUID only among
  the requesting user's accounts (400 otherwise).
- Create, defense in depth: `AccountOwnerCreateMixin.create` re-checks
  every validated related object before `perform_create` runs and
  returns 403 if any belongs to an account the user does not own.
"""

# system imports
from typing import Any

# 3rd party imports
from django.db.models import Model, QuerySet
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

# Project imports
from .models import (
    BankAccount,
    Budget,
    FundingEventOccurrence,
    InternalTransaction,
    Transaction,
    TransactionAllocation,
)


####################################################################
#
def get_bank_account(obj: object) -> BankAccount | None:
    """Resolve the BankAccount from any moneypools domain object.

    Args:
        obj: A moneypools model instance.

    Returns:
        The related BankAccount, or None if it cannot be resolved.
    """
    match obj:
        case BankAccount():
            return obj
        case Budget() | Transaction() | InternalTransaction():
            return obj.bank_account
        case TransactionAllocation():
            return obj.transaction.bank_account
        case FundingEventOccurrence():
            return obj.budget.bank_account
        case _:
            return None


########################################################################
########################################################################
#
class IsAccountOwner(BasePermission):
    """Object-level permission that grants access if the requesting
    user is in the related bank account's 'owners' M2M.

    This covers retrieve, update, partial update, delete and detail
    actions, which all go through `get_object()`.  It has no effect on
    list views -- use `AccountOwnerQuerySetMixin` to filter querysets
    instead -- and none on create, because `CreateModelMixin` never
    calls `get_object()`.  Create is covered by `OwnedBankAccountField`
    on the serializer and by `AccountOwnerCreateMixin.create`.
    """

    ####################################################################
    #
    def has_object_permission(
        self, request: Request, view: APIView, obj: object
    ) -> bool:
        """Check whether the requesting user owns the related account.

        Args:
            request: The incoming DRF request.
            view: The view being accessed.
            obj: The object being checked.

        Returns:
            True if the user is an owner of the related bank account.
        """
        bank_account = get_bank_account(obj)
        if bank_account is None:
            return False
        return bank_account.owners.filter(pk=request.user.pk).exists()


########################################################################
########################################################################
#
class AccountOwnerCreateMixin:
    """ViewSet mixin that re-checks ownership of related objects named
    in a create request before `perform_create` runs.

    Serializers scope writable `bank_account` fields with
    `OwnedBankAccountField`; this mixin is the fallback that keeps
    create failing closed if a serializer declares an unscoped related
    field.  It defines `create`, which makes the router expose POST, so
    apply it only to viewsets that already support create (i.e. that
    include `CreateModelMixin`).  Must appear before the ViewSet class
    in the MRO.
    """

    ####################################################################
    #
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Validate, verify related-object ownership, then create.

        Mirrors `CreateModelMixin.create`, with `check_create_ownership`
        run between validation and `perform_create`, so the check holds
        even when a view overrides `perform_create`.

        Args:
            request: The incoming DRF request.
            *args: Positional arguments forwarded from the router.
            **kwargs: Keyword arguments forwarded from the router.

        Returns:
            A 201 response with the serialized new object.

        Raises:
            PermissionDenied: If a related object belongs to a bank
                account the requesting user does not own.
        """
        serializer = self.get_serializer(data=request.data)  # type: ignore[attr-defined]
        serializer.is_valid(raise_exception=True)
        self.check_create_ownership(serializer.validated_data)
        self.perform_create(serializer)  # type: ignore[attr-defined]
        headers = self.get_success_headers(serializer.data)  # type: ignore[attr-defined]
        return Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )

    ####################################################################
    #
    def check_create_ownership(self, validated_data: dict[str, Any]) -> None:
        """Require every account-owned related object to be the user's.

        Resolves each validated model instance (e.g. `bank_account`,
        `src_budget`, `transaction`), including those inside list
        values from `many=True` fields, to its bank account via
        `get_bank_account` and checks the requesting user is an owner.
        Values that do not resolve to a bank account (e.g. a `Bank` or a
        `TransactionCategory`) are skipped.  Serializers already scope
        these fields, so this only fails when a serializer declares an
        unscoped related field.

        Args:
            validated_data: The serializer's validated data.

        Raises:
            PermissionDenied: If any related object belongs to a bank
                account the requesting user does not own.
        """
        user = self.request.user  # type: ignore[attr-defined]
        values: list[Any] = []
        for value in validated_data.values():
            if isinstance(value, list | tuple):
                values.extend(value)
            else:
                values.append(value)
        for value in values:
            if not isinstance(value, Model):
                continue
            bank_account = get_bank_account(value)
            if bank_account is None:
                continue
            if not bank_account.owners.filter(pk=user.pk).exists():
                raise PermissionDenied(
                    "You do not have permission to perform this action."
                )


########################################################################
########################################################################
#
class AccountOwnerQuerySetMixin:
    """ViewSet mixin that filters querysets to only include objects
    belonging to bank accounts the requesting user owns.

    Must appear before the ViewSet class in the MRO so that
    'get_queryset' is called correctly.
    """

    ####################################################################
    #
    def get_queryset(self) -> QuerySet:
        """Filter the base queryset to objects the user owns.

        Determines the ownership lookup path based on the model:
        BankAccount uses 'owners', Budget/Transaction/InternalTransaction
        use 'bank_account__owners', and TransactionAllocation uses
        'transaction__bank_account__owners'.

        Returns:
            A queryset filtered to the requesting user's owned objects.
        """
        qs = super().get_queryset()  # type: ignore[misc]
        user = self.request.user  # type: ignore[attr-defined]
        model = qs.model

        if model is BankAccount:
            return qs.filter(owners=user)

        # Budget, Transaction, InternalTransaction all have a direct
        # 'bank_account' FK.
        #
        if hasattr(model, "bank_account"):
            return qs.filter(bank_account__owners=user)

        # TransactionAllocation goes through transaction.bank_account.
        #
        if hasattr(model, "transaction"):
            return qs.filter(transaction__bank_account__owners=user)

        return qs.none()
