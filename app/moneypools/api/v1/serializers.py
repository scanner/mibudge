"""
DRF serializers for the moneypools domain.

Each serializer controls which fields are readable vs writable and
enforces invariants that the model layer does not (e.g. allocation
sums, same-account constraints for internal transactions).

Fields marked 'editable=False' on the model are read-only by default
in DRF.  Where those fields must be set at creation time (bank_account,
amount, etc.) we declare them explicitly to override the auto-generated
read-only version.

djmoney stores monetary values as a pair: a DecimalField for the amount
and a CharField for the currency (suffixed '_currency').  Its DRF
integration (``djmoney.contrib.django_rest_framework.MoneyField``)
auto-registers into ``ModelSerializer.serializer_field_mapping`` so
that model ``MoneyField`` instances produce the correct DRF field.
The DRF ``MoneyField.get_value()`` reads the ``<field>_currency``
key directly from raw request data, so serializers should NOT declare
explicit ``_currency`` CharField overrides -- the ``_currency`` model
fields appear as read-only CharFields for response output while input
currency is handled automatically by the ``MoneyField``.
"""

# system imports
from datetime import datetime
from decimal import Decimal

# 3rd party imports
import recurrence
from django.db.models import Sum
from djmoney.contrib.django_rest_framework import MoneyField as DRFMoneyField
from rest_framework import serializers

# Project imports
from moneypools.models import (
    DECIMAL_PLACES,
    MAX_DIGITS,
    Bank,
    BankAccount,
    Budget,
    InternalTransaction,
    Transaction,
    TransactionAllocation,
    TransactionCategory,
    get_default_currency,
)
from moneypools.service import funding as funding_svc


########################################################################
########################################################################
#
class RecurrenceSerializerField(serializers.CharField):
    """Serialize django-recurrence values as RFC 2445 strings.

    Accepts iCal recurrence strings like 'RRULE:FREQ=MONTHLY' on
    input and returns the same format on output.  Blank and null
    handling is delegated to the CharField base via 'allow_blank'
    and 'allow_null' -- 'to_internal_value' always receives a
    non-empty string.
    """

    ####################################################################
    #
    def to_internal_value(self, data: str) -> recurrence.Recurrence:
        """Deserialize an RFC 2445 string to a Recurrence object.

        Args:
            data: An iCal recurrence string (e.g. 'RRULE:FREQ=MONTHLY').

        Returns:
            A recurrence.Recurrence instance.

        Raises:
            ValidationError: If the string cannot be parsed.
        """
        try:
            return recurrence.deserialize(data)
        except (ValueError, TypeError) as e:
            raise serializers.ValidationError(
                f"Invalid recurrence string: {e}"
            ) from e

    ####################################################################
    #
    def to_representation(
        self, value: recurrence.Recurrence | None
    ) -> str | None:
        """Serialize a Recurrence object to an RFC 2445 string.

        Args:
            value: A recurrence.Recurrence instance, or None.

        Returns:
            The iCal string representation, or None if the value is
            null.
        """
        if value is None:
            return None
        return recurrence.serialize(value)


########################################################################
########################################################################
#
class BankSerializer(serializers.ModelSerializer):
    """Read-only serializer for banks.

    Banks are shared reference data managed only through the admin.
    """

    class Meta:
        model = Bank
        fields = [
            "id",
            "name",
            "routing_number",
            "default_currency",
            "created_at",
            "modified_at",
        ]
        read_only_fields = fields


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


########################################################################
########################################################################
#
class BudgetSerializer(serializers.ModelSerializer):
    """Serializer for budgets.

    On create the caller supplies bank_account (UUID) and budget
    properties.  After creation, bank_account and budget_type are
    immutable.  Balance is managed by signals and is always read-only.
    The unallocated budget's name cannot be changed.

    Currency is inherited from the bank account via the pre_save
    signal and is not accepted from the client.
    """

    # bank_account is editable=False on the model.  Override for create.
    #
    bank_account = serializers.SlugRelatedField(
        slug_field="id",
        queryset=BankAccount.objects.all(),
    )

    # djmoney's auto-mapped DRF MoneyField reads default_currency from
    # the model field, but doesn't call it when it's a callable.
    # Override to resolve it at import time.
    #
    target_balance = DRFMoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default_currency=get_default_currency(),
    )
    funding_amount = DRFMoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default_currency=get_default_currency(),
        required=False,
        allow_null=True,
    )

    funding_schedule = RecurrenceSerializerField(
        required=False, allow_blank=True
    )
    recurrance_schedule = RecurrenceSerializerField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )

    next_funding = serializers.SerializerMethodField()

    class Meta:
        model = Budget
        fields = [
            "id",
            "name",
            "bank_account",
            "balance",
            "balance_currency",
            "target_balance",
            "target_balance_currency",
            "funding_amount",
            "funding_amount_currency",
            "budget_type",
            "funding_type",
            "target_date",
            "with_fillup_goal",
            "fillup_goal",
            "archived",
            "archived_at",
            "complete",
            "paused",
            "funding_schedule",
            "recurrance_schedule",
            "memo",
            "auto_spend",
            "next_funding",
            "created_at",
            "modified_at",
        ]
        read_only_fields = [
            "id",
            "balance",
            "balance_currency",
            "target_balance_currency",
            "funding_amount_currency",
            "complete",
            "archived",
            "archived_at",
            "created_at",
            "modified_at",
        ]

    ####################################################################
    #
    def get_next_funding(self, obj: Budget) -> dict | None:
        """Return the next scheduled funding event for this budget, or null.

        Args:
            obj: The Budget instance being serialized.

        Returns:
            Dict with 'date', 'amount', 'amount_currency', 'deferred', or None.
        """
        info = funding_svc.next_funding_info(obj)
        if info is None:
            return None
        return {
            "date": info.date.isoformat(),
            "amount": str(info.amount.amount),
            "amount_currency": str(info.amount.currency),
            "deferred": info.deferred,
        }

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
    def validate_budget_type(self, value: str) -> str:
        """Prevent changing budget_type after creation.

        Args:
            value: The budget type choice value.

        Returns:
            The validated budget type.

        Raises:
            ValidationError: If this is an update and the type differs.
        """
        if self.instance is not None and self.instance.budget_type != value:
            raise serializers.ValidationError(
                "Cannot change the budget type after creation."
            )
        return value

    ####################################################################
    #
    def validate_name(self, value: str) -> str:
        """Prevent renaming the unallocated budget.

        Args:
            value: The proposed budget name.

        Returns:
            The validated name.

        Raises:
            ValidationError: If this is the unallocated budget and the
                name is being changed.
        """
        if self.instance is not None:
            bank_account = self.instance.bank_account
            if (
                bank_account.unallocated_budget_id == self.instance.id
                and value != self.instance.name
            ):
                raise serializers.ValidationError(
                    "Cannot rename the unallocated budget."
                )
        return value


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
    # create.
    #
    bank_account = serializers.SlugRelatedField(
        slug_field="id",
        queryset=BankAccount.objects.all(),
    )
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
    # cross-account linker (moneypools.linking). Exposed as a plain
    # UUID so the UI can render an affordance without needing a full
    # nested serializer round-trip. Read-only: linking is controlled
    # server-side, never by the client.
    #
    linked_transaction = serializers.SlugRelatedField(
        slug_field="id", read_only=True
    )

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
        read_only_fields = [
            "id",
            "amount_currency",
            "party",
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
    # create.
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
            "memo",
            "created_at",
            "modified_at",
        ]
        read_only_fields = [
            "id",
            "amount_currency",
            "budget_balance",
            "budget_balance_currency",
            "created_at",
            "modified_at",
        ]

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
    def validate_category(self, value: str) -> str:
        """Validate the category is a known TransactionCategory value.

        Args:
            value: The category string.

        Returns:
            The validated category string.

        Raises:
            ValidationError: If the category is not a valid choice.
        """
        valid = {c.value for c in TransactionCategory}
        if value not in valid:
            raise serializers.ValidationError(
                f"'{value}' is not a valid transaction category."
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
    # create.
    #
    bank_account = serializers.SlugRelatedField(
        slug_field="id",
        queryset=BankAccount.objects.all(),
    )
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
