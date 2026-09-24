"""
Serializers for bank transactions in the moneypools v1 API.

Holds the transaction serializer plus the request bodies of the
transaction actions: `TransactionSplitsSerializer` for `splits` and
`ResolvePendingSerializer` for `resolve-pending`.
"""

# system imports
from datetime import datetime
from decimal import Decimal

# 3rd party imports
from djmoney.contrib.django_rest_framework import MoneyField as DRFMoneyField
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

# Project imports
from moneypools.models import (
    DECIMAL_PLACES,
    MAX_DIGITS,
    BankAccount,
    Transaction,
    TransactionCategory,
    get_default_currency,
)

from .fields import OwnedBankAccountField


########################################################################
########################################################################
#
class TransactionSerializer(serializers.ModelSerializer):
    """Serializer for bank transactions.

    On create the caller supplies bank_account, amount,
    transaction_date, transaction_type, raw_description, and
    optionally pending, memo, and description.

    After creation only transaction_type, memo, and description are
    updatable.  The view is responsible for creating the default
    TransactionAllocation to the unallocated budget on create.

    The ``amount_currency`` is read from raw request data by
    djmoney's ``MoneyField.get_value()`` -- no explicit currency
    field declaration is needed.
    """

    # These fields are editable=False on the model.  Override for
    # create.  `OwnedBankAccountField` resolves the UUID only among the
    # requesting user's accounts.
    #
    bank_account = OwnedBankAccountField()
    amount = DRFMoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default_currency=get_default_currency(),
    )
    # Bank-supplied settlement date -- always required on create.
    posted_date = serializers.DateTimeField()
    # Purchase date derived from the description.  Optional on create:
    # when omitted the service derives it via parse_transaction_date.
    # Read-only on update (immutable after creation like posted_date).
    transaction_date = serializers.DateTimeField(
        required=False, allow_null=True, default=None, read_only=False
    )
    pending = serializers.BooleanField(default=False)
    raw_description = serializers.CharField(max_length=512)

    # description is populated from raw_description by the pre_save
    # signal if not provided.
    #
    description = serializers.CharField(
        max_length=512, required=False, allow_blank=True
    )

    # Counterpart on another account, populated asynchronously by the
    # Bank-supplied stable per-transaction identifier.  editable=False
    # on the model, so must be declared explicitly to be writable here.
    # Writable on both create (importer supplies it) and PATCH (backfill
    # for transactions imported before this field existed).
    #
    bank_transaction_id = serializers.CharField(
        max_length=256, required=False, allow_null=True, allow_blank=True
    )

    # cross-account linker (moneypools.linking). Exposed as a plain
    # UUID so the UI can render an affordance without needing a full
    # nested serializer round-trip. Read-only: linking is controlled
    # server-side, never by the client.
    #
    linked_transaction = serializers.SlugRelatedField(
        slug_field="id", read_only=True
    )

    # What the transaction was spent on.  Nullable (null = unassigned);
    # user-editable.  Exposed as the category UUID; the read-only
    # category_full_name saves the UI a lookup for display.  The
    # unscoped queryset is narrowed by `validate_category`, which
    # requires `TransactionCategory.objects.visible_to(user)`.
    #
    category = serializers.SlugRelatedField(
        slug_field="id",
        queryset=TransactionCategory.objects.all(),
        required=False,
        allow_null=True,
    )
    category_full_name = serializers.SerializerMethodField()

    # Whether the transaction-details import pipeline has enriched
    # this row.  The raw details JSON itself is not exposed; the
    # extracted merchant_* columns are.
    has_details = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = [
            "id",
            "bank_account",
            "amount",
            "amount_currency",
            "party",
            "posted_date",
            "transaction_date",
            "transaction_type",
            "pending",
            "memo",
            "raw_description",
            "description",
            "description_user_edited",
            "category",
            "category_full_name",
            "merchant_name",
            "merchant_intermediary",
            "merchant_address",
            "merchant_city",
            "merchant_region",
            "merchant_country",
            "merchant_latitude",
            "merchant_longitude",
            "merchant_category",
            "merchant_category_code",
            "virtual_card_number",
            "has_details",
            "bank_transaction_id",
            "linked_transaction",
            "bank_account_posted_balance",
            "bank_account_posted_balance_currency",
            "bank_account_available_balance",
            "bank_account_available_balance_currency",
            "image",
            "document",
            "created_at",
            "modified_at",
        ]
        # The merchant identity columns (merchant_name,
        # merchant_category, merchant_category_code,
        # virtual_card_number) are editable=False on the model, so the
        # ModelSerializer maps them read-only automatically.  The six
        # merchant location fields stay writable -- users may refine
        # or supply the merchant's actual address / map coordinates.
        read_only_fields = [
            "id",
            "amount_currency",
            "party",
            "description_user_edited",
            "category_full_name",
            "has_details",
            "linked_transaction",
            "bank_account_posted_balance",
            "bank_account_posted_balance_currency",
            "bank_account_available_balance",
            "bank_account_available_balance_currency",
            "created_at",
            "modified_at",
        ]

    ####################################################################
    #
    @extend_schema_field(serializers.BooleanField())
    def get_has_details(self, obj: Transaction) -> bool:
        """Return True when the details import has enriched this row."""
        return obj.details is not None

    ####################################################################
    #
    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_category_full_name(self, obj: Transaction) -> str | None:
        """Return the category's '{group} : {name}' display form, or null."""
        return obj.category.full_name if obj.category is not None else None

    ####################################################################
    #
    def validate_category(
        self, value: TransactionCategory | None
    ) -> TransactionCategory | None:
        """Require the category to be visible to the requesting user.

        Args:
            value: The TransactionCategory resolved from the UUID, or
                None when clearing.

        Returns:
            The validated category (or None).

        Raises:
            ValidationError: If the category is not visible to the
                requesting user.
        """
        request = self.context.get("request")
        if value is None or request is None:
            return value
        visible = TransactionCategory.objects.visible_to(request.user)
        if not visible.filter(pk=value.pk).exists():
            raise serializers.ValidationError(
                "Not a transaction category visible to you."
            )
        return value

    ####################################################################
    #
    def validate_bank_account(self, value: BankAccount) -> BankAccount:
        """Prevent changing the bank account after creation.

        Args:
            value: The BankAccount instance resolved from the UUID.

        Returns:
            The validated BankAccount instance.

        Raises:
            ValidationError: If this is an update.
        """
        if self.instance is not None:
            raise serializers.ValidationError(
                "Cannot change the bank account after creation."
            )
        return value

    ####################################################################
    #
    def validate_amount(self, value: Decimal) -> Decimal:
        """Prevent changing the amount after creation.

        Args:
            value: The transaction amount (Decimal or Money).

        Returns:
            The validated amount.

        Raises:
            ValidationError: If this is an update.
        """
        if self.instance is not None:
            raise serializers.ValidationError(
                "Cannot change the transaction amount after creation."
            )
        return value

    ####################################################################
    #
    def validate_posted_date(self, value: datetime) -> datetime:
        """Prevent changing the posted date after creation.

        Args:
            value: The posted datetime.

        Returns:
            The validated datetime.

        Raises:
            ValidationError: If this is an update.
        """
        if self.instance is not None:
            raise serializers.ValidationError(
                "Cannot change the posted date after creation."
            )
        return value

    ####################################################################
    #
    def validate_transaction_date(
        self, value: datetime | None
    ) -> datetime | None:
        """Prevent changing the transaction date after creation.

        Args:
            value: The transaction datetime, or None.

        Returns:
            The validated datetime, or None.

        Raises:
            ValidationError: If this is an update.
        """
        if self.instance is not None and value is not None:
            raise serializers.ValidationError(
                "Cannot change the transaction date after creation."
            )
        return value

    ####################################################################
    #
    def validate_raw_description(self, value: str) -> str:
        """Prevent changing raw_description after creation.

        Args:
            value: The raw description string.

        Returns:
            The validated string.

        Raises:
            ValidationError: If this is an update.
        """
        if self.instance is not None:
            raise serializers.ValidationError(
                "Cannot change the raw description after creation."
            )
        return value

    ####################################################################
    #
    def validate_pending(self, value: bool) -> bool:
        """Prevent reverting a posted transaction back to pending.

        The pending → posted transition is valid (normal settlement flow)
        and is handled by TransactionService.update().  The reverse is
        not meaningful and is rejected.

        Args:
            value: The pending flag.

        Returns:
            The validated flag.

        Raises:
            ValidationError: If attempting to set pending=True on a
                transaction that is already posted.
        """
        if (
            self.instance is not None
            and value is True
            and not self.instance.pending
        ):
            raise serializers.ValidationError(
                "Cannot revert a posted transaction to pending."
            )
        return value


########################################################################
########################################################################
#
class TransactionSplitsSerializer(serializers.Serializer):
    """Serializer for the declarative splits endpoint.

    Accepts a dict mapping budget UUIDs to amounts.  The backend
    reconciles existing allocations to match the declared state.
    Any remainder goes to the unallocated budget.

    All budgets must belong to the same bank account as the
    transaction.  Cross-account budget references are rejected
    with a 400 error.
    """

    splits = serializers.DictField(
        child=serializers.DecimalField(
            max_digits=MAX_DIGITS,
            decimal_places=DECIMAL_PLACES,
        ),
        allow_empty=True,
        help_text=(
            "Map of budget UUID → amount.  Amounts must not exceed "
            "the transaction total.  Omitted remainder is assigned "
            "to the unallocated budget."
        ),
    )

    def validate_splits(self, value: dict[str, Decimal]) -> dict[str, Decimal]:
        """Validate that all declared amounts are positive numbers."""
        for budget_id, amount in value.items():
            if amount <= 0:
                raise serializers.ValidationError(
                    f"Amount for budget {budget_id} must be positive."
                )
        return value


########################################################################
########################################################################
#
class ResolvePendingSerializer(serializers.Serializer):
    """Input serializer for the resolve-pending action.

    Validates the settled posted_date and optional final amount.
    Requires ``transaction`` in the serializer context for sign validation.
    """

    posted_date = serializers.DateTimeField()
    amount = DRFMoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default_currency=get_default_currency(),
        required=False,
        allow_null=True,
    )

    ####################################################################
    #
    def validate(self, attrs: dict) -> dict:
        """Reject amount sign changes relative to the original transaction.

        Args:
            attrs: Validated field data.

        Returns:
            The validated attrs dict.

        Raises:
            ValidationError: If the supplied amount has the wrong sign.
        """
        amount = attrs.get("amount")
        transaction = self.context.get("transaction")
        if amount is not None and transaction is not None:
            if (amount.amount > 0) != (transaction.amount.amount > 0):
                raise serializers.ValidationError(
                    {
                        "amount": (
                            "Amount sign must match the original transaction."
                        )
                    }
                )
        return attrs
