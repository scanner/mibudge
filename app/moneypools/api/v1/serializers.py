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
from django.db.models import Q, Sum
from djmoney.contrib.django_rest_framework import MoneyField as DRFMoneyField
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

# Project imports
from moneypools.models import (
    DECIMAL_PLACES,
    MAX_DIGITS,
    Bank,
    BankAccount,
    BankAccountInvitation,
    Budget,
    FundingEventOccurrence,
    InternalTransaction,
    Transaction,
    TransactionAllocation,
    TransactionCategory,
    get_default_currency,
)
from moneypools.service import categories as categories_svc
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


########################################################################
########################################################################
#
class TransactionCategorySerializer(serializers.ModelSerializer):
    """Serializer for transaction categories.

    On create the caller supplies group and name; the view forces the
    owner to the requesting user (global rows are managed via the
    django-admin only).  Group and name are whitespace-normalized and
    checked case-insensitively against the global rows and the user's
    own rows for duplicates.  'archived' is toggled via the archive
    action, not writable here.
    """

    owner = serializers.SlugRelatedField(
        slug_field="username",
        read_only=True,
        help_text="Owner username; null for a global category.",
    )
    full_name = serializers.CharField(
        read_only=True,
        help_text="Canonical display form: '{group} : {name}'.",
    )

    class Meta:
        model = TransactionCategory
        fields = [
            "id",
            "group",
            "name",
            "full_name",
            "owner",
            "archived",
            "created_at",
            "modified_at",
        ]
        read_only_fields = [
            "id",
            "full_name",
            "owner",
            "archived",
            "created_at",
            "modified_at",
        ]

    ####################################################################
    #
    def validate_group(self, value: str) -> str:
        """Normalize whitespace and reject colons in the group.

        A colon in the group would break the first-colon split used
        everywhere full names are parsed (export/import, resolver).

        Args:
            value: The proposed group string.

        Returns:
            The whitespace-normalized group.

        Raises:
            ValidationError: If the group is empty or contains a colon.
        """
        value = " ".join(value.split())
        if not value:
            raise serializers.ValidationError("Group must not be empty.")
        if ":" in value:
            raise serializers.ValidationError("Group must not contain a colon.")
        return value

    ####################################################################
    #
    def validate_name(self, value: str) -> str:
        """Normalize whitespace in the name.

        Args:
            value: The proposed name string.

        Returns:
            The whitespace-normalized name.

        Raises:
            ValidationError: If the name is empty.
        """
        value = " ".join(value.split())
        if not value:
            raise serializers.ValidationError("Name must not be empty.")
        return value

    ####################################################################
    #
    def validate(self, attrs: dict) -> dict:
        """Reject case-insensitive duplicates of global or own rows.

        Duplicates of other users' shared categories are allowed --
        those live in the other user's namespace.

        Args:
            attrs: The validated field data.

        Returns:
            The validated attrs dict.

        Raises:
            ValidationError: If an equivalent global or own category
                already exists.
        """
        group = attrs.get(
            "group", self.instance.group if self.instance else None
        )
        name = attrs.get("name", self.instance.name if self.instance else None)
        request = self.context.get("request")
        user = request.user if request is not None else None

        dup_scope = Q(owner__isnull=True)
        if user is not None:
            dup_scope |= Q(owner=user)
        duplicates = TransactionCategory.objects.filter(
            dup_scope, group__iexact=group, name__iexact=name
        )
        if self.instance is not None:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise serializers.ValidationError(
                f"A category '{group} : {name}' already exists."
            )
        return attrs


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
    recurrence_schedule = RecurrenceSerializerField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text=(
            "Refresh cycle for Recurring budgets.  Restricted grammar: "
            "a single RRULE whose FREQ is WEEKLY, MONTHLY, or YEARLY "
            "with an optional INTERVAL, plus an optional DTSTART that "
            "anchors the day the cycle refreshes on (e.g. "
            "'DTSTART:20260708T000000Z RRULE:FREQ=MONTHLY' refreshes "
            "on the 8th of every month).  BY* parts, COUNT, UNTIL, and "
            "exception rules/dates are rejected -- the anchor date is "
            "the only day-of-cycle control.  The funding_schedule "
            "field is not restricted this way."
        ),
    )

    next_funding = serializers.SerializerMethodField()
    next_recurrence = serializers.SerializerMethodField()
    funding_pace = serializers.SerializerMethodField()

    class Meta:
        model = Budget
        fields = [
            "id",
            "name",
            "bank_account",
            "balance",
            "balance_currency",
            "funded_amount",
            "funded_amount_currency",
            "target_balance",
            "target_balance_currency",
            "funding_amount",
            "funding_amount_currency",
            "budget_type",
            "funding_type",
            "target_date",
            "fillup_goal",
            "archived",
            "archived_at",
            "complete",
            "paused",
            "funding_schedule",
            "recurrence_schedule",
            "memo",
            "auto_spend",
            "next_funding",
            "next_recurrence",
            "funding_pace",
            "created_at",
            "modified_at",
        ]
        read_only_fields = [
            "id",
            "balance",
            "balance_currency",
            "funded_amount",
            "funded_amount_currency",
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
            Dict with 'date', 'amount', 'amount_currency', or None.
        """
        info = funding_svc.next_funding_info(obj)
        if info is None:
            return None
        return {
            "date": info.date.isoformat(),
            "amount": str(info.amount.amount),
            "amount_currency": str(info.amount.currency),
        }

    ####################################################################
    #
    def get_next_recurrence(self, obj: Budget) -> str | None:
        """Return the date of the next recurrence (refresh) event, or null.

        The recurrence_schedule's DTSTART is only the rule's anchor;
        this field is the actual upcoming refresh date (first
        occurrence after last_recurrence_on).  Only Recurring budgets
        have one.

        Args:
            obj: The Budget instance being serialized.

        Returns:
            ISO date string, or None.
        """
        d = funding_svc.next_recurrence_date(obj)
        return d.isoformat() if d is not None else None

    ####################################################################
    #
    @extend_schema_field(
        serializers.ChoiceField(
            choices=list(funding_svc.FUNDING_PACE_CHOICES),
            allow_null=True,
        )
    )
    def get_funding_pace(self, obj: Budget) -> str | None:
        """Return how the goal's funding compares to its plan, or null.

        Computed server-side from funded_amount against the fraction of
        scheduled funding events elapsed -- independent of the balance,
        so pre-spending a goal does not read as behind pace.  Null for
        non-goal budgets and goals where pace does not apply (paused,
        archived, complete, no target date).

        Args:
            obj: The Budget instance being serialized.

        Returns:
            'ahead', 'on_track', 'behind', or None.
        """
        return funding_svc.funding_pace(obj)

    ####################################################################
    #
    def validate_recurrence_schedule(
        self, value: recurrence.Recurrence | str | None
    ) -> recurrence.Recurrence | str | None:
        """Restrict the refresh cycle to the supported grammar.

        A recurrence_schedule is a simple cycle (weekly, monthly, or
        yearly, with an optional interval) anchored by an optional
        DTSTART that supplies the refresh day.  Richer RFC 2445 shapes
        (BY* parts, COUNT, UNTIL, exception rules/dates, multiple
        rules) are rejected: BY* parts silently override the DTSTART
        anchor during evaluation, and the funding engine assumes one
        boundary per cycle.  The funding_schedule field keeps the full
        grammar; only the refresh cycle is restricted.

        Args:
            value: The deserialized Recurrence, or None/'' when the
                schedule is being cleared.

        Returns:
            The validated value unchanged.

        Raises:
            ValidationError: If the rule falls outside the supported
                grammar.
        """
        if not isinstance(value, recurrence.Recurrence):
            # None (cleared) or '' (blank) -- nothing to validate.
            return value

        if value.exrules or value.rdates or value.exdates:
            raise serializers.ValidationError(
                "recurrence_schedule does not support exception rules "
                "(EXRULE), extra dates (RDATE), or excluded dates "
                "(EXDATE)."
            )

        if len(value.rrules) != 1:
            raise serializers.ValidationError(
                "recurrence_schedule must contain exactly one RRULE."
            )

        rule = value.rrules[0]

        if rule.freq not in (
            recurrence.WEEKLY,
            recurrence.MONTHLY,
            recurrence.YEARLY,
        ):
            raise serializers.ValidationError(
                "recurrence_schedule FREQ must be WEEKLY, MONTHLY, or YEARLY."
            )

        if rule.interval < 1:
            raise serializers.ValidationError(
                "recurrence_schedule INTERVAL must be a positive integer."
            )

        if rule.count is not None or rule.until is not None:
            raise serializers.ValidationError(
                "recurrence_schedule does not support COUNT or UNTIL; "
                "a refresh cycle does not end."
            )

        by_parts = (
            rule.byday,
            rule.bymonthday,
            rule.bymonth,
            rule.byyearday,
            rule.byweekno,
            rule.bysetpos,
            rule.byhour,
            rule.byminute,
            rule.bysecond,
        )
        if any(by_parts):
            raise serializers.ValidationError(
                "recurrence_schedule does not support BY* rule parts; "
                "use DTSTART to anchor the day the cycle refreshes on."
            )

        return value

    ####################################################################
    #
    def validate_auto_spend(self, value: list) -> list:
        """Validate and canonicalize auto-spend matcher entries.

        Each entry must be a string that resolves (case-insensitively,
        whitespace-normalized) to a transaction category visible to
        the requesting user.  Entries are rewritten to the matched
        category's canonical full name ('{group} : {name}').

        Args:
            value: The auto_spend list from the request.

        Returns:
            The list with entries canonicalized.

        Raises:
            ValidationError: If an entry is not a string or does not
                resolve to a visible category.
        """
        request = self.context.get("request")
        if request is not None:
            visible = TransactionCategory.objects.visible_to(request.user)
        else:
            visible = TransactionCategory.objects.all()

        canonical: list[str] = []
        for entry in value:
            if not isinstance(entry, str):
                raise serializers.ValidationError(
                    "auto_spend entries must be strings."
                )
            group, name = categories_svc.normalize_category(entry)
            if not group:
                raise serializers.ValidationError(
                    "auto_spend entries must not be empty."
                )
            category = visible.filter(
                group__iexact=group, name__iexact=name
            ).first()
            if category is None:
                raise serializers.ValidationError(
                    f"'{entry}' does not match any transaction category "
                    "visible to you."
                )
            canonical.append(category.full_name)
        return canonical

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
    # category_full_name saves the UI a lookup for display.
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

    # What this portion was spent on.  Nullable (null = unassigned).
    # Defaults to the transaction's category at creation (service-layer
    # copy hook); edits never propagate between transaction and
    # allocation afterwards.
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


########################################################################
########################################################################
#
class ScrapeSyncTransactionSerializer(serializers.Serializer):
    """One transaction in a scrape-sync payload.

    Mirrors `service.sync_scrape.ScrapedTransaction`.  Pending rows
    carry the scrape's local `posted_date` (banks typically render
    pending rows without a real settlement date -- e.g. BofA shows
    'Processing' in the date column -- and the scraper substitutes
    the current local datetime).  Posted rows carry the bank-supplied
    settlement datetime.  `transaction_date` is derived server-side
    from the embedded MM/DD pattern in `raw_description`.

    `running_balance` is optional and used only for the posting-order
    sanity walk; never persisted.
    """

    is_pending = serializers.BooleanField()
    posted_date = serializers.DateTimeField()
    raw_description = serializers.CharField(max_length=512)
    amount = DRFMoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default_currency=get_default_currency(),
    )
    transaction_type = serializers.CharField(
        max_length=32, required=False, allow_blank=True, default=""
    )
    running_balance = serializers.DecimalField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        required=False,
        allow_null=True,
        default=None,
    )


########################################################################
########################################################################
#
class ScrapeSyncSerializer(serializers.Serializer):
    """Input serializer for the bank-account scrape-sync action.

    Validates a full bank-side snapshot for one account: when the
    scrape was taken, the bank's ending available balance, and the
    list of transactions (newest-first as the bank renders them).
    """

    scraped_at = serializers.DateTimeField()
    ending_balance = DRFMoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default_currency=get_default_currency(),
    )
    transactions = ScrapeSyncTransactionSerializer(many=True)


########################################################################
########################################################################
#
class ScrapeSyncDetailsNeededSerializer(serializers.Serializer):
    """One posted scrape row still needing a transaction-details fetch.

    `index` is the row's position in the SUBMITTED transactions array
    (exact correlation back to the scraper's own rows); `transaction`
    is the DB row the fetched details should be applied to via the
    transaction-details action.
    """

    index = serializers.IntegerField()
    transaction = serializers.UUIDField()


########################################################################
########################################################################
#
class ScrapeSyncReportSerializer(serializers.Serializer):
    """Output serializer for the bank-account scrape-sync action.

    Mirrors `service.sync_scrape.ScrapeSyncReport`.  Reports
    everything the caller needs to summarise what changed and surface
    validation warnings.
    """

    deleted_pending = serializers.IntegerField()
    inserted_posted = serializers.IntegerField()
    skipped_posted = serializers.IntegerField()
    inserted_pending = serializers.IntegerField()
    balance_mismatch = serializers.DecimalField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        allow_null=True,
    )
    posting_order_mismatches = serializers.ListField(
        child=serializers.CharField()
    )
    last_posted_through = serializers.DateField(allow_null=True)
    new_transaction_ids = serializers.ListField(child=serializers.UUIDField())
    details_needed = ScrapeSyncDetailsNeededSerializer(many=True)


########################################################################
########################################################################
#
class TransactionDetailsItemSerializer(serializers.Serializer):
    """One (transaction, raw details dict) pair to apply.

    The details dict is stored verbatim on the transaction (it is the
    provenance record); the service extracts the merchant columns and
    the category hint from it.
    """

    transaction = serializers.UUIDField()
    details = serializers.DictField()


########################################################################
########################################################################
#
class TransactionDetailsSerializer(serializers.Serializer):
    """Input serializer for the bank-account transaction-details action.

    `overwrite` re-applies scraper-owned fields on rows already
    enriched (location fields and an assigned category are still
    never clobbered).
    """

    overwrite = serializers.BooleanField(default=False)
    details = TransactionDetailsItemSerializer(many=True)


########################################################################
########################################################################
#
class TransactionDetailsResultSerializer(serializers.Serializer):
    """Per-item outcome of the transaction-details action."""

    transaction = serializers.UUIDField()
    status = serializers.ChoiceField(
        choices=[
            "applied",
            "skipped_has_details",
            "skipped_pending",
            "not_found",
        ]
    )
    warnings = serializers.ListField(child=serializers.CharField())


########################################################################
########################################################################
#
class TransactionDetailsReportSerializer(serializers.Serializer):
    """Output serializer for the bank-account transaction-details action."""

    applied = serializers.IntegerField()
    skipped_has_details = serializers.IntegerField()
    skipped_pending = serializers.IntegerField()
    not_found = serializers.IntegerField()
    results = TransactionDetailsResultSerializer(many=True)


########################################################################
########################################################################
#
class FundingEventOccurrenceSerializer(serializers.ModelSerializer):
    """Read-only serializer for FundingEventOccurrence rows.

    Exposes the budget UUID as 'budget' rather than the internal pkid so
    callers can cross-reference with the Budget endpoint.
    """

    budget = serializers.UUIDField(source="budget.id", read_only=True)

    class Meta:
        model = FundingEventOccurrence
        fields = [
            "id",
            "budget",
            "kind",
            "scheduled_date",
            "status",
            "completed_at",
            "created_at",
            "modified_at",
        ]
        read_only_fields = fields


########################################################################
########################################################################
#
class BankAccountInvitationSerializer(serializers.ModelSerializer):
    """Read-only serializer for BankAccountInvitation rows.

    ``token`` is included so the SPA can construct the cancel URL without a
    separate lookup.  It is safe to expose to authenticated account owners
    since they created the invitation and the cancel endpoint enforces that
    only the sender may cancel.

    ``bank_account_id`` and ``bank_account_name`` are included for the
    cross-account listing on the user's settings page (me/invitations/).
    """

    invited_by = serializers.EmailField(
        source="invited_by.email", read_only=True, default=None
    )
    bank_account_id = serializers.UUIDField(
        source="bank_account.id", read_only=True
    )
    bank_account_name = serializers.CharField(
        source="bank_account.name", read_only=True
    )

    class Meta:
        model = BankAccountInvitation
        fields = [
            "id",
            "token",
            "bank_account_id",
            "bank_account_name",
            "invitee_email",
            "invited_by",
            "status",
            "expires_at",
            "accepted_at",
            "declined_at",
            "cancelled_at",
            "created_at",
            "modified_at",
        ]
        read_only_fields = fields


########################################################################
########################################################################
#
class InviteOwnerSerializer(serializers.Serializer):
    """Write-only serializer for the invite-owner action."""

    invitee_email = serializers.EmailField()

    def validate_invitee_email(self, value: str) -> str:
        return value.strip().lower()


########################################################################
########################################################################
#
class PublicInvitationDetailSerializer(serializers.ModelSerializer):
    """Read-only serializer for the public invitation-detail endpoint.

    Returns the minimum information needed to render the acceptance page
    for API clients.  Owner names are intentionally minimal (display name
    or email only) to limit PII exposure behind a bare token.
    """

    bank_account_name = serializers.CharField(
        source="bank_account.name", read_only=True
    )
    bank_name = serializers.CharField(
        source="bank_account.bank.name", read_only=True
    )
    current_owners = serializers.SerializerMethodField()
    is_new_user = serializers.SerializerMethodField()

    class Meta:
        model = BankAccountInvitation
        fields = [
            "id",
            "status",
            "invitee_email",
            "bank_account_name",
            "bank_name",
            "current_owners",
            "is_new_user",
            "expires_at",
        ]
        read_only_fields = fields

    def get_current_owners(self, obj: BankAccountInvitation) -> list[str]:
        return [u.name or u.email for u in obj.bank_account.owners.all()]

    def get_is_new_user(self, obj: BankAccountInvitation) -> bool:
        return (
            obj.invitee_user is not None
            and not obj.invitee_user.has_usable_password()
        )
