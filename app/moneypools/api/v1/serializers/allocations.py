"""
Serializer for transaction allocations in the moneypools v1 API.

`TransactionAllocationSerializer` maps a portion of a transaction's
amount to a budget and enforces the same-account and allocation-sum
invariants.
"""

# system imports
from decimal import Decimal

# 3rd party imports
from django.db.models import Sum
from djmoney.contrib.django_rest_framework import MoneyField as DRFMoneyField
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

# Project imports
from moneypools.models import (
    DECIMAL_PLACES,
    MAX_DIGITS,
    Budget,
    Transaction,
    TransactionAllocation,
    TransactionCategory,
    get_default_currency,
)


########################################################################
########################################################################
#
class TransactionAllocationSerializer(serializers.ModelSerializer):
    """Serializer for transaction allocations.

    An allocation maps a portion of a transaction's amount to a budget.
    On create the caller supplies transaction, amount, and optionally
    budget (defaults to unallocated) and category.  After creation,
    budget, category, and memo are updatable.

    The serializer enforces two key constraints:

    1. **Same-account restriction** -- the budget must belong to the
       same bank account as the transaction.  Cross-account allocations
       are rejected with a 400 error.
    2. **Sum constraint** -- the total allocated amount across all
       allocations for a transaction must not exceed the transaction
       amount.

    The ``amount_currency`` is read from raw request data by
    djmoney's ``MoneyField.get_value()`` -- no explicit currency
    field declaration is needed.
    """

    # These fields are editable=False on the model.  Override for
    # create.  `TransactionAllocationViewSet` is read-only (allocations
    # are written through the transaction `splits` action, which scopes
    # budgets to the transaction's account in `transaction_svc.split`),
    # so no endpoint writes through `transaction` or `budget` here.
    # `validate` also requires `budget` to share the transaction's bank
    # account.  A future writable allocation endpoint must scope
    # `transaction` to the requesting user's accounts.
    #
    transaction = serializers.SlugRelatedField(
        slug_field="id",
        queryset=Transaction.objects.all(),
    )
    amount = DRFMoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default_currency=get_default_currency(),
    )
    budget = serializers.SlugRelatedField(
        slug_field="id",
        queryset=Budget.objects.all(),
        required=False,
        allow_null=True,
    )

    # What this portion was spent on.  Nullable (null = unassigned).
    # Defaults to the transaction's category at creation (service-layer
    # copy hook); edits never propagate between transaction and
    # allocation afterwards.  Visibility is checked in
    # `validate_category` via `TransactionCategory.objects.visible_to`.
    #
    category = serializers.SlugRelatedField(
        slug_field="id",
        queryset=TransactionCategory.objects.all(),
        required=False,
        allow_null=True,
    )
    category_full_name = serializers.SerializerMethodField()

    class Meta:
        model = TransactionAllocation
        fields = [
            "id",
            "transaction",
            "budget",
            "amount",
            "amount_currency",
            "budget_balance",
            "budget_balance_currency",
            "category",
            "category_full_name",
            "memo",
            "created_at",
            "modified_at",
        ]
        read_only_fields = [
            "id",
            "amount_currency",
            "budget_balance",
            "budget_balance_currency",
            "category_full_name",
            "created_at",
            "modified_at",
        ]

    ####################################################################
    #
    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_category_full_name(self, obj: TransactionAllocation) -> str | None:
        """Return the category's '{group} : {name}' display form, or null."""
        return obj.category.full_name if obj.category is not None else None

    ####################################################################
    #
    def validate_transaction(self, value: Transaction) -> Transaction:
        """Prevent changing the transaction after creation.

        Args:
            value: The Transaction instance resolved from the UUID.

        Returns:
            The validated Transaction instance.

        Raises:
            ValidationError: If this is an update.
        """
        if self.instance is not None:
            raise serializers.ValidationError(
                "Cannot change the transaction after creation."
            )
        return value

    ####################################################################
    #
    def validate_amount(self, value: Decimal) -> Decimal:
        """Validate the allocation amount.

        Ensures the sign of the amount does not change on update
        (prevents flipping a debit to a credit or vice-versa).

        Args:
            value: The allocation amount (Decimal or Money).

        Returns:
            The validated amount.

        Raises:
            ValidationError: If the sign would change.
        """
        if self.instance is not None:
            old_amount = self.instance.amount
            old_val = (
                old_amount.amount
                if hasattr(old_amount, "amount")
                else old_amount
            )
            new_val = value.amount if hasattr(value, "amount") else value
            if (old_val > 0) != (new_val > 0) and new_val != 0:
                raise serializers.ValidationError(
                    "Cannot change the sign of an allocation amount."
                )
        return value

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
    def validate(self, attrs: dict) -> dict:
        """Validate cross-field constraints for allocations.

        Checks:
        1. The budget belongs to the same bank account as the
           transaction.
        2. Total allocations do not exceed the transaction amount.

        Args:
            attrs: The validated field data.

        Returns:
            The validated attrs dict.

        Raises:
            ValidationError: If the budget is from a different account
                or the allocation total would exceed the transaction
                amount.
        """
        if self.instance is not None:
            transaction = self.instance.transaction
            new_amount = attrs.get("amount", self.instance.amount)
        else:
            transaction = attrs["transaction"]
            new_amount = attrs["amount"]

        budget = attrs.get(
            "budget",
            self.instance.budget if self.instance else None,
        )
        if budget is not None:
            if budget.bank_account_id != transaction.bank_account_id:
                raise serializers.ValidationError(
                    {
                        "budget": (
                            "Budget does not belong to the same "
                            "bank account as the transaction."
                        )
                    }
                )

        existing_qs = TransactionAllocation.objects.filter(
            transaction=transaction
        )
        if self.instance is not None:
            existing_qs = existing_qs.exclude(id=self.instance.id)

        existing_total = existing_qs.aggregate(total=Sum("amount"))[
            "total"
        ] or Decimal("0")

        # Transaction amounts can be negative (debits) so compare
        # absolute values.  new_amount may be a Money instance from
        # djmoney so extract the decimal amount if needed.
        #
        tx_abs = abs(transaction.amount.amount)
        new_decimal = (
            abs(new_amount.amount)
            if hasattr(new_amount, "amount")
            else abs(new_amount)
        )
        alloc_abs = abs(existing_total) + new_decimal

        if alloc_abs > tx_abs:
            raise serializers.ValidationError(
                f"Total allocations ({alloc_abs}) would exceed "
                f"the transaction amount ({tx_abs})."
            )
        return attrs
