"""
Serializer for budgets (virtual envelopes) in the moneypools v1 API.

`BudgetSerializer` validates budget type, target and funding-schedule
invariants and exposes the derived funding fields.
"""

# 3rd party imports
import recurrence
from djmoney.contrib.django_rest_framework import MoneyField as DRFMoneyField
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

# Project imports
from moneypools.models import (
    DECIMAL_PLACES,
    MAX_DIGITS,
    BankAccount,
    Budget,
    TransactionCategory,
    get_default_currency,
)
from moneypools.service import categories as categories_svc
from moneypools.service import funding as funding_svc

from .fields import OwnedBankAccountField, RecurrenceSerializerField


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
    # `OwnedBankAccountField` resolves the UUID only among the requesting
    # user's accounts, so a budget cannot be created in another user's
    # account.
    #
    bank_account = OwnedBankAccountField()

    # `fillup_goal` is set by `budget_svc` when it creates a Recurring
    # budget's fill-up child.  Read-only here so a request body cannot
    # point it at an arbitrary budget, including one in another user's
    # account (the service mirrors parent edits onto the fill-up goal).
    #
    fillup_goal = serializers.SlugRelatedField(
        slug_field="id", read_only=True, allow_null=True
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
