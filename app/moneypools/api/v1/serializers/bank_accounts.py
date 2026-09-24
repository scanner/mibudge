"""
Serializer for bank accounts in the moneypools v1 API.

`BankAccountSerializer` backs the `/bank-accounts/` CRUD endpoints and
the response of the bank-account import actions.
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
    Bank,
    BankAccount,
    get_default_currency,
)


########################################################################
########################################################################
#
class BankAccountSerializer(serializers.ModelSerializer):
    """Serializer for bank accounts.

    On create the caller supplies name, bank (UUID), account_type,
    account_number, and optionally currency and initial balances.
    The view routes creation through BankAccountService which adds
    the requesting user as owner and seeds the Unallocated budget.

    After creation, name and account_number are updatable.  Currency,
    account_type, bank, and balances are immutable once the account
    exists.

    Group assignment is not yet supported via the API.
    """

    # bank is editable=False on the model so DRF makes it read-only.
    # Override to make it writable on create.
    #
    bank = serializers.SlugRelatedField(
        slug_field="id",
        queryset=Bank.objects.all(),
    )

    # Return usernames instead of raw PKs so the frontend can display
    # owner identities without a separate user lookup.
    #
    owners = serializers.SlugRelatedField(
        slug_field="username",
        many=True,
        read_only=True,
    )

    # Balances are editable=False on the model.  Override with
    # djmoney's DRF MoneyField so they can be set on create
    # (e.g. when importing an existing account with a balance).
    # They default to 0 and are immutable after creation.
    # The _currency fields are read-only -- the pre_save signal
    # aligns balance currencies with the account's currency.
    #
    posted_balance = DRFMoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        required=False,
        default_currency=get_default_currency(),
    )
    available_balance = DRFMoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        required=False,
        default_currency=get_default_currency(),
    )

    class Meta:
        model = BankAccount
        fields = [
            "id",
            "name",
            "bank",
            "owners",
            "account_type",
            "account_number",
            "currency",
            "posted_balance",
            "posted_balance_currency",
            "available_balance",
            "available_balance_currency",
            "unallocated_budget",
            "auto_funding_enabled",
            "last_imported_at",
            "last_posted_through",
            "created_at",
            "modified_at",
        ]
        read_only_fields = [
            "id",
            "owners",
            "posted_balance_currency",
            "available_balance_currency",
            "unallocated_budget",
            "last_imported_at",
            "last_posted_through",
            "created_at",
            "modified_at",
        ]
        extra_kwargs = {
            "account_number": {"required": False},
        }

    ####################################################################
    #
    def validate_account_number(self, value: str | None) -> str | None:
        """Require account_number on create; allow updates.

        Args:
            value: The account number string, or None.

        Returns:
            The validated value.

        Raises:
            ValidationError: If creating and no account number supplied.
        """
        if self.instance is None and not value:
            raise serializers.ValidationError("Account number is required.")
        return value

    ####################################################################
    #
    def validate_bank(self, value: Bank) -> Bank:
        """Prevent changing the bank after creation.

        Args:
            value: The Bank instance resolved from the UUID.

        Returns:
            The validated Bank instance.

        Raises:
            ValidationError: If this is an update and the bank differs.
        """
        if self.instance is not None and self.instance.bank != value:
            raise serializers.ValidationError(
                "Cannot change the bank after account creation."
            )
        return value

    ####################################################################
    #
    def validate_account_type(self, value: str) -> str:
        """Prevent changing account_type after creation.

        Args:
            value: The account type choice value.

        Returns:
            The validated account type.

        Raises:
            ValidationError: If this is an update and the type differs.
        """
        if self.instance is not None and self.instance.account_type != value:
            raise serializers.ValidationError(
                "Cannot change the account type after creation."
            )
        return value

    ####################################################################
    #
    def validate_currency(self, value: str) -> str:
        """Prevent changing the currency after creation.

        Args:
            value: The ISO 4217 currency code.

        Returns:
            The validated currency code.

        Raises:
            ValidationError: If this is an update and the currency
                differs.
        """
        if self.instance is not None and self.instance.currency != value:
            raise serializers.ValidationError(
                "Cannot change the currency after account creation."
            )
        return value

    ####################################################################
    #
    def validate_posted_balance(self, value: Decimal) -> Decimal:
        """Prevent changing the posted balance after creation.

        Args:
            value: The posted balance amount (Decimal or Money).

        Returns:
            The validated value.

        Raises:
            ValidationError: If this is an update.
        """
        if self.instance is not None:
            raise serializers.ValidationError(
                "Cannot change the posted balance after creation."
            )
        return value

    ####################################################################
    #
    def validate_available_balance(self, value: Decimal) -> Decimal:
        """Prevent changing the available balance after creation.

        Args:
            value: The available balance amount (Decimal or Money).

        Returns:
            The validated value.

        Raises:
            ValidationError: If this is an update.
        """
        if self.instance is not None:
            raise serializers.ValidationError(
                "Cannot change the available balance after creation."
            )
        return value
