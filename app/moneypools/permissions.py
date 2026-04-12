"""
DRF permissions for the moneypools domain.

All permissions are at the BankAccount level. A user who is in a bank
account's 'owners' M2M has full access to the account and all its
related objects (budgets, transactions, allocations, internal
transactions).

Banks are shared reference data and require only authentication.
"""

# 3rd party imports
from django.db.models import QuerySet
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

# Project imports
from .models import BankAccount


####################################################################
#
def get_bank_account(obj: object) -> BankAccount | None:
    """Resolve the BankAccount from any moneypools domain object.

    Handles BankAccount directly, Budget/Transaction/InternalTransaction
    (all have a direct 'bank_account' FK), and TransactionAllocation
    (which goes through 'transaction.bank_account').

    Args:
        obj: A moneypools model instance.

    Returns:
        The related BankAccount, or None if it cannot be resolved.
    """
    if isinstance(obj, BankAccount):
        return obj
    if hasattr(obj, "bank_account"):
        return obj.bank_account
    if hasattr(obj, "transaction"):
        return obj.transaction.bank_account
    return None


########################################################################
########################################################################
#
class IsAccountOwner(BasePermission):
    """Object-level permission that grants access if the requesting
    user is in the related bank account's 'owners' M2M.

    For list views this has no effect -- use AccountOwnerQuerySetMixin
    to filter querysets instead.
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
