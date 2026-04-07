"""Django admin configuration for all moneypools models."""

# system imports
#
from typing import Any

# 3rd party imports
#
from django import forms
from django.contrib import admin
from django.contrib.admin.widgets import AdminDateWidget
from django.core.exceptions import ValidationError
from django.db import models
from django.http import HttpRequest

# Project imports
#
from .models import (
    DECIMAL_PLACES,
    MAX_DIGITS,
    Bank,
    BankAccount,
    Budget,
    InternalTransaction,
    Transaction,
    TransactionAllocation,
)

########################################################################
########################################################################
#
# Custom forms for models with editable=False fields that need to be
# settable on creation. Django's ModelForm metaclass rejects
# editable=False fields in Meta.fields, so we declare them as explicit
# form fields and set Meta.fields = ().
#


class BankForm(forms.ModelForm):
    """Allow setting routing_number on creation."""

    class Meta:
        model = Bank
        fields = ("name",)

    # editable=False on the model, declared explicitly for creation.
    routing_number = forms.CharField(max_length=9, required=False)


class BankAccountForm(forms.ModelForm):
    """Allow setting bank, account_number, and initial balances on creation."""

    class Meta:
        model = BankAccount
        # Editable model fields handled by Django's ModelForm machinery.
        fields = ("name", "account_type", "owners", "group")

    # editable=False model fields declared explicitly so the creation
    # form can set them.
    bank = forms.ModelChoiceField(queryset=Bank.objects.all())
    account_number = forms.CharField(max_length=12, required=False)
    posted_balance = forms.DecimalField(
        max_digits=MAX_DIGITS, decimal_places=DECIMAL_PLACES, required=False
    )
    available_balance = forms.DecimalField(
        max_digits=MAX_DIGITS, decimal_places=DECIMAL_PLACES, required=False
    )


class BudgetForm(forms.ModelForm):
    """Allow setting bank_account on creation."""

    class Meta:
        model = Budget
        # Editable model fields handled by Django's ModelForm machinery.
        fields = (
            "name",
            "budget_type",
            "funding_type",
            "balance",
            "target_balance",
            "target_date",
            "funding_schedule",
            "recurrance_schedule",
            "with_fillup_goal",
            "fillup_goal",
            "paused",
            "memo",
            "image",
        )
        widgets = {
            "target_date": AdminDateWidget,
        }

    # editable=False model field declared explicitly so the creation
    # form can set it.
    bank_account: forms.ModelChoiceField = forms.ModelChoiceField(
        queryset=BankAccount.objects.all()
    )


########################################################################
########################################################################
#
class BudgetInline(admin.TabularInline):
    model = Budget
    extra = 0
    fields = (
        "name",
        "budget_type",
        "balance",
        "target_balance",
        "funding_type",
        "paused",
        "archived",
    )
    readonly_fields = ("balance", "archived")
    show_change_link = True


########################################################################
########################################################################
#
class TransactionAllocationInline(admin.TabularInline):
    model = TransactionAllocation
    extra = 0
    fields = ("budget", "amount", "category", "budget_balance", "memo")
    readonly_fields = ("amount", "budget_balance")


########################################################################
########################################################################
#
@admin.register(Bank)
class BankAdmin(admin.ModelAdmin):
    list_display = ("name", "routing_number", "id")
    search_fields = ("name", "routing_number")
    fields = ("name", "routing_number")

    ####################################################################
    #
    def get_form(
        self,
        request: HttpRequest,
        obj: Any | None = None,
        change: bool = False,
        **kwargs: Any,
    ) -> type[forms.ModelForm]:
        if obj is None:
            return BankForm
        kwargs["fields"] = ("name",)
        return super().get_form(request, obj, change=change, **kwargs)

    ####################################################################
    #
    def get_readonly_fields(
        self, request: HttpRequest, obj: Bank | None = None
    ) -> tuple[str, ...]:
        """Allow routing_number on creation, read-only after."""
        if obj is None:
            return ()
        return ("routing_number",)


########################################################################
########################################################################
#
@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "bank",
        "account_type",
        "posted_balance",
        "available_balance",
        "id",
    )
    list_filter = ("account_type", "bank")
    search_fields = ("name", "account_number")
    filter_horizontal = ("owners",)
    inlines = [BudgetInline]

    # Show fields that are normally hidden due to editable=False so they
    # are visible in the detail view and settable on creation.
    #
    fields = (
        "name",
        "bank",
        "account_type",
        "account_number",
        "owners",
        "group",
        "posted_balance",
        "available_balance",
        "unallocated_budget",
    )

    ####################################################################
    #
    def get_form(
        self,
        request: HttpRequest,
        obj: Any | None = None,
        change: bool = False,
        **kwargs: Any,
    ) -> type[forms.ModelForm]:
        if obj is None:
            return BankAccountForm
        # Existing object: editable=False fields are all in
        # readonly_fields so only pass the truly editable ones.
        kwargs["fields"] = ("name", "account_type", "owners", "group")
        return super().get_form(request, obj, change=change, **kwargs)

    ####################################################################
    #
    def get_readonly_fields(
        self, request: HttpRequest, obj: BankAccount | None = None
    ) -> tuple[str, ...]:
        """
        On creation: allow setting bank, account_number, and initial
        balances. After creation: these become read-only because signals
        manage balance updates and the bank/account_number are immutable.
        """
        if obj is None:
            return ("unallocated_budget",)
        return (
            "bank",
            "account_number",
            "posted_balance",
            "available_balance",
            "unallocated_budget",
        )


########################################################################
########################################################################
#
@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "bank_account",
        "budget_type",
        "funding_type",
        "balance",
        "target_balance",
        "paused",
        "archived",
    )
    list_filter = ("budget_type", "funding_type", "archived", "paused")
    search_fields = ("name",)
    formfield_overrides = {
        models.DateField: {"widget": AdminDateWidget},
    }

    # Show bank_account which is normally hidden due to editable=False.
    #
    fields = (
        "name",
        "bank_account",
        "budget_type",
        "funding_type",
        "balance",
        "target_balance",
        "target_date",
        "funding_schedule",
        "recurrance_schedule",
        "with_fillup_goal",
        "fillup_goal",
        "paused",
        "archived",
        "archived_at",
        "memo",
        "image",
    )

    ####################################################################
    #
    def get_form(
        self,
        request: HttpRequest,
        obj: Any | None = None,
        change: bool = False,
        **kwargs: Any,
    ) -> type[forms.ModelForm]:
        if obj is None:
            return BudgetForm
        # Existing object: bank_account is in readonly_fields so
        # exclude it from the form fields.
        kwargs["fields"] = (
            "name",
            "budget_type",
            "funding_type",
            "balance",
            "target_balance",
            "target_date",
            "funding_schedule",
            "recurrance_schedule",
            "with_fillup_goal",
            "fillup_goal",
            "paused",
            "memo",
            "image",
        )
        return super().get_form(request, obj, change=change, **kwargs)

    ####################################################################
    #
    def get_readonly_fields(
        self, request: HttpRequest, obj: Budget | None = None
    ) -> tuple[str, ...]:
        """
        On creation: allow setting bank_account. After creation:
        bank_account is immutable, archived fields are signal-managed.
        """
        if obj is None:
            return ("archived", "archived_at")
        return ("bank_account", "archived", "archived_at")


########################################################################
########################################################################
#
@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        "transaction_date",
        "description",
        "amount",
        "bank_account",
        "pending",
        "transaction_type",
    )
    list_filter = (
        "pending",
        "transaction_type",
        "bank_account",
    )
    search_fields = ("description", "raw_description", "party")
    date_hierarchy = "transaction_date"
    inlines = [TransactionAllocationInline]

    # Transactions come from imports. Show fields normally hidden due to
    # editable=False so they are visible in the detail view.
    #
    fields = (
        "bank_account",
        "transaction_date",
        "amount",
        "transaction_type",
        "pending",
        "description",
        "raw_description",
        "party",
        "memo",
        "bank_account_posted_balance",
        "bank_account_available_balance",
        "image",
        "document",
    )
    readonly_fields = (
        "amount",
        "bank_account",
        "party",
        "transaction_date",
        "pending",
        "raw_description",
        "bank_account_posted_balance",
        "bank_account_available_balance",
    )


########################################################################
########################################################################
#
@admin.register(TransactionAllocation)
class TransactionAllocationAdmin(admin.ModelAdmin):
    list_display = (
        "transaction",
        "budget",
        "amount",
        "category",
    )
    list_filter = ("category", "budget")
    search_fields = ("memo",)
    fields = (
        "transaction",
        "budget",
        "amount",
        "category",
        "budget_balance",
        "memo",
    )
    readonly_fields = ("transaction", "amount", "budget_balance")


########################################################################
########################################################################
#
class InternalTransactionForm(forms.ModelForm):
    """
    Custom form for creating InternalTransactions via admin.

    The model marks key fields as editable=False so Django's default
    ModelForm excludes them. We explicitly include them here so the
    admin creation form works.
    """

    class Meta:
        model = InternalTransaction
        fields = ()

    amount: forms.DecimalField = forms.DecimalField(
        max_digits=MAX_DIGITS, decimal_places=DECIMAL_PLACES
    )
    src_budget: forms.ModelChoiceField = forms.ModelChoiceField(
        queryset=Budget.objects.all()
    )
    dst_budget: forms.ModelChoiceField = forms.ModelChoiceField(
        queryset=Budget.objects.all()
    )

    ####################################################################
    #
    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        assert cleaned is not None
        src = cleaned.get("src_budget")
        dst = cleaned.get("dst_budget")
        amount = cleaned.get("amount")

        if src and dst and src == dst:
            raise ValidationError(
                "Source and destination budgets must be different."
            )

        if src and dst and src.bank_account != dst.bank_account:
            raise ValidationError(
                "Source and destination budgets must belong to the same "
                "bank account."
            )

        if src and amount is not None and src.balance.amount < amount:
            raise ValidationError(
                f"Source budget '{src.name}' has insufficient funds "
                f"({src.balance}). Cannot transfer {amount}."
            )

        if amount is not None and amount <= 0:
            raise ValidationError("Amount must be greater than zero.")

        return cleaned


########################################################################
########################################################################
#
@admin.register(InternalTransaction)
class InternalTransactionAdmin(admin.ModelAdmin):
    """Admin for write-once internal transactions."""

    list_display = (
        "created_at",
        "amount",
        "src_budget",
        "dst_budget",
        "actor",
        "bank_account",
    )
    list_filter = ("bank_account",)

    ####################################################################
    #
    def get_form(
        self,
        request: HttpRequest,
        obj: Any | None = None,
        change: bool = False,
        **kwargs: Any,
    ) -> type[forms.ModelForm]:
        """
        Use our custom form for creation. For viewing existing records,
        use a bare ModelForm with no fields -- the admin renders
        everything via readonly_fields instead.
        """
        if obj is None:
            return InternalTransactionForm
        # Existing object: everything is readonly, so the form needs
        # no model fields at all.
        kwargs["fields"] = ()
        return super().get_form(request, obj, change=change, **kwargs)

    ####################################################################
    #
    def get_fields(
        self, request: HttpRequest, obj: InternalTransaction | None = None
    ) -> tuple[str, ...]:
        """Show editable fields on creation, all fields when viewing."""
        if obj is None:
            return ("amount", "src_budget", "dst_budget")
        return (
            "bank_account",
            "amount",
            "src_budget",
            "dst_budget",
            "actor",
            "src_budget_balance",
            "dst_budget_balance",
        )

    ####################################################################
    #
    def get_readonly_fields(
        self, request: HttpRequest, obj: InternalTransaction | None = None
    ) -> tuple[str, ...]:
        """All fields are read-only after creation."""
        if obj is None:
            return ()
        return (
            "amount",
            "bank_account",
            "src_budget",
            "dst_budget",
            "actor",
            "src_budget_balance",
            "dst_budget_balance",
        )

    ####################################################################
    #
    def save_model(
        self,
        request: HttpRequest,
        obj: InternalTransaction,
        form: InternalTransactionForm,
        change: bool,
    ) -> None:
        """Set actor and bank_account automatically on creation."""
        if not change:
            obj.actor_id = int(request.user.pk)  # type: ignore[arg-type]
            obj.bank_account = obj.src_budget.bank_account
        super().save_model(request, obj, form, change)

    ####################################################################
    #
    def has_change_permission(
        self, request: HttpRequest, obj: InternalTransaction | None = None
    ) -> bool:
        """Write-once: no editing after creation."""
        if obj is not None:
            return False
        return super().has_change_permission(request, obj)
