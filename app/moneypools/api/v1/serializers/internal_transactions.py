"""
Serializer for budget-to-budget transfers in the moneypools v1 API.

`InternalTransactionSerializer` validates that both budgets belong to
the same bank account; internal transactions are write-once.
"""

# system imports
from decimal import Decimal

# 3rd party imports
from djmoney.contrib.django_rest_framework import MoneyField as DRFMoneyField
from rest_framework import serializers

# Project imports
from moneypools.models import (
    DECIMAL_PLACES,
    MAX_DIGITS,
    Budget,
    InternalTransaction,
    get_default_currency,
)

from .fields import OwnedBankAccountField


########################################################################
########################################################################
#
class InternalTransactionSerializer(serializers.ModelSerializer):
    """Serializer for internal transactions (budget-to-budget transfers).

    Internal transactions are write-once: the API supports create and
    read but not update or delete.  To reverse a transfer, create a
    new internal transaction with the src and dst budgets swapped.

    On create the caller supplies bank_account, amount, src_budget,
    and dst_budget.  The view sets the actor to the requesting user.

    The ``amount_currency`` is read from raw request data by
    djmoney's ``MoneyField.get_value()`` -- no explicit currency
    field declaration is needed.
    """

    # All these fields are editable=False on the model.  Override for
    # create.  `OwnedBankAccountField` resolves the UUID only among the
    # requesting user's accounts; `validate` then requires both budgets
    # to belong to that account, which scopes them transitively.
    #
    bank_account = OwnedBankAccountField()
    amount = DRFMoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default_currency=get_default_currency(),
    )
    src_budget = serializers.SlugRelatedField(
        slug_field="id",
        queryset=Budget.objects.all(),
    )
    dst_budget = serializers.SlugRelatedField(
        slug_field="id",
        queryset=Budget.objects.all(),
    )

    effective_date = serializers.DateTimeField(required=False, default=None)

    class Meta:
        model = InternalTransaction
        fields = [
            "id",
            "bank_account",
            "amount",
            "amount_currency",
            "src_budget",
            "dst_budget",
            "actor",
            "effective_date",
            "src_budget_balance",
            "src_budget_balance_currency",
            "dst_budget_balance",
            "dst_budget_balance_currency",
            "created_at",
            "modified_at",
        ]
        read_only_fields = [
            "id",
            "amount_currency",
            "actor",
            "src_budget_balance",
            "src_budget_balance_currency",
            "dst_budget_balance",
            "dst_budget_balance_currency",
            "created_at",
            "modified_at",
        ]

    ####################################################################
    #
    def validate_amount(self, value: Decimal) -> Decimal:
        """Validate that the transfer amount is positive.

        Args:
            value: The transfer amount (Decimal or Money).

        Returns:
            The validated amount.

        Raises:
            ValidationError: If the amount is not positive.
        """
        # value may be a Money instance from djmoney.
        #
        raw = value.amount if hasattr(value, "amount") else value
        if raw <= 0:
            raise serializers.ValidationError(
                "Transfer amount must be positive."
            )
        return value

    ####################################################################
    #
    def validate(self, attrs: dict) -> dict:
        """Validate cross-field constraints for internal transactions.

        Ensures that src and dst budgets are different and both belong
        to the specified bank account.

        Args:
            attrs: The validated field data.

        Returns:
            The validated attrs dict.

        Raises:
            ValidationError: If constraints are violated.
        """
        bank_account = attrs["bank_account"]
        src_budget = attrs["src_budget"]
        dst_budget = attrs["dst_budget"]

        if src_budget == dst_budget:
            raise serializers.ValidationError(
                "Source and destination budgets must be different."
            )
        if src_budget.bank_account != bank_account:
            raise serializers.ValidationError(
                {
                    "src_budget": (
                        "Source budget does not belong to "
                        "the specified bank account."
                    )
                }
            )
        if dst_budget.bank_account != bank_account:
            raise serializers.ValidationError(
                {
                    "dst_budget": (
                        "Destination budget does not belong to "
                        "the specified bank account."
                    )
                }
            )
        return attrs
