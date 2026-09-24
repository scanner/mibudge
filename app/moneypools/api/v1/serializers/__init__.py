"""
DRF serializers for the moneypools domain.

Each serializer controls which fields are readable vs writable and
enforces invariants that the model layer does not (e.g. allocation
sums, same-account constraints for internal transactions).

Serializers live in per-domain modules (`bank_accounts`, `budgets`,
`transactions`, `imports`, ...); custom fields shared between them live
in `fields`.  This package re-exports every serializer so external
callers import from `moneypools.api.v1.serializers`; code inside the
v1 API imports from the specific module.

Fields marked 'editable=False' on the model are read-only by default
in DRF.  Where those fields must be set at creation time (bank_account,
amount, etc.) we declare them explicitly to override the auto-generated
read-only version.

djmoney stores monetary values as a pair: a DecimalField for the amount
and a CharField for the currency (suffixed '_currency').  Its DRF
integration (`djmoney.contrib.django_rest_framework.MoneyField`)
auto-registers into `ModelSerializer.serializer_field_mapping` so
that model `MoneyField` instances produce the correct DRF field.
The DRF `MoneyField.get_value()` reads the `<field>_currency`
key directly from raw request data, so serializers should NOT declare
explicit `_currency` CharField overrides -- the `_currency` model
fields appear as read-only CharFields for response output while input
currency is handled automatically by the `MoneyField`.
"""

# Project imports
from .allocations import TransactionAllocationSerializer
from .bank_accounts import BankAccountSerializer
from .budgets import BudgetSerializer
from .categories import TransactionCategorySerializer
from .fields import (
    OwnedBankAccountField,
    RecurrenceSerializerField,
)
from .funding import FundingEventOccurrenceSerializer
from .imports import (
    ScrapeSyncDetailsNeededSerializer,
    ScrapeSyncReportSerializer,
    ScrapeSyncSerializer,
    ScrapeSyncTransactionSerializer,
    TransactionDetailsItemSerializer,
    TransactionDetailsReportSerializer,
    TransactionDetailsResultSerializer,
    TransactionDetailsSerializer,
)
from .internal_transactions import InternalTransactionSerializer
from .invitations import (
    BankAccountInvitationSerializer,
    InviteOwnerSerializer,
    PublicInvitationDetailSerializer,
)
from .reference import BankSerializer
from .transactions import (
    ResolvePendingSerializer,
    TransactionSerializer,
    TransactionSplitsSerializer,
)

__all__ = [
    "RecurrenceSerializerField",
    "BankSerializer",
    "BankAccountSerializer",
    "TransactionCategorySerializer",
    "BudgetSerializer",
    "TransactionSerializer",
    "TransactionAllocationSerializer",
    "TransactionSplitsSerializer",
    "InternalTransactionSerializer",
    "ResolvePendingSerializer",
    "ScrapeSyncTransactionSerializer",
    "ScrapeSyncSerializer",
    "ScrapeSyncDetailsNeededSerializer",
    "ScrapeSyncReportSerializer",
    "TransactionDetailsItemSerializer",
    "TransactionDetailsSerializer",
    "TransactionDetailsResultSerializer",
    "TransactionDetailsReportSerializer",
    "FundingEventOccurrenceSerializer",
    "BankAccountInvitationSerializer",
    "InviteOwnerSerializer",
    "PublicInvitationDetailSerializer",
    "OwnedBankAccountField",
]
