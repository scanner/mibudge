"""
DRF viewsets for the moneypools domain.

All viewsets use UUID-based lookup (`id` field) and require JWT
authentication.  Object-level access is enforced by
`AccountOwnerQuerySetMixin` (filters list queries to owned objects)
and `IsAccountOwner` (guards retrieve/update/delete on individual
objects).  Create is scoped by `OwnedBankAccountField` on the
serializer and re-checked by `AccountOwnerCreateMixin`.

Banks are read-only reference data.  All other resources support the
standard CRUD operations with restrictions documented per-viewset.

Views live in per-domain modules (`bank_accounts`, `budgets`,
`transactions`, ...).  `BankAccountViewSet`'s `@action` endpoints live
in mixins in `imports`, `funding` and `invitations`; see the
`bank_accounts` module docstring for the map.  This package re-exports
every view so `config.api_router` imports from
`moneypools.api.v1.views`.
"""

# Project imports
from .bank_accounts import BankAccountViewSet
from .budgets import BudgetViewSet
from .categories import TransactionCategoryViewSet
from .funding import FundingEventOccurrenceViewSet
from .internal_transactions import InternalTransactionViewSet
from .invitations import (
    invitation_accept,
    invitation_decline,
    invitation_detail,
)
from .reference import (
    BankViewSet,
    currencies,
)
from .transactions import (
    TransactionAllocationViewSet,
    TransactionViewSet,
)

__all__ = [
    "BankViewSet",
    "BankAccountViewSet",
    "BudgetViewSet",
    "TransactionCategoryViewSet",
    "TransactionViewSet",
    "TransactionAllocationViewSet",
    "InternalTransactionViewSet",
    "FundingEventOccurrenceViewSet",
    "currencies",
    "invitation_detail",
    "invitation_accept",
    "invitation_decline",
]
