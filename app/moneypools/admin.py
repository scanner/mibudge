"""Django admin configuration for all moneypools models."""

# system imports
#
from typing import Any

# 3rd party imports
#
from django import forms
from django.contrib import admin
from django.contrib.admin.widgets import AdminDateWidget, AdminSplitDateTime
from django.core.exceptions import ValidationError
from django.db import models
from django.http import HttpRequest
from djmoney.money import Money

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
from .service import bank_account as bank_account_svc
from .service import budget as budget_svc
from .service import internal_transaction as itx_svc

########################################################################
########################################################################
#
# Custom forms for models with editable=False fields that need to be
# settable on creation. Django's ModelForm metaclass rejects
# editable=False fields in Meta.fields, so we declare them as explicit
# form fields and set Meta.fields = ().
#


####################################################################
#
def _apply_extra_fields(
    form: forms.ModelForm, field_names: tuple[str, ...]
) -> None:
    """
    Copy declared form fields (outside Meta.fields) onto the instance.

    Django's ModelForm.save() only applies fields listed in Meta.fields
    to self.instance. Fields declared on the form that correspond to
    editable=False model attributes are left in cleaned_data and never
    written to the instance, which yields NOT NULL integrity errors on
    save. Call this from save() to push those values through.
    """
    for name in field_names:
        if name in form.cleaned_data:
            value = form.cleaned_data[name]
            if value is not None:
                setattr(form.instance, name, value)


class BankAccountForm(forms.ModelForm):
    """Allow setting bank and initial balances on creation."""

    class Meta:
        model = BankAccount
        # Editable model fields handled by Django's ModelForm machinery.
        # account_number is editable on the model -- it can be filled
        # in later, so it belongs to the regular ModelForm machinery
        # rather than the editable=False override path below.
        fields = (
            "name",
            "account_type",
            "account_number",
            "owners",
            "group",
            "link_aliases",
        )

    # editable=False model fields declared explicitly so the creation
    # form can set them.
    bank = forms.ModelChoiceField(queryset=Bank.objects.all())
    posted_balance = forms.DecimalField(
        max_digits=MAX_DIGITS, decimal_places=DECIMAL_PLACES, required=False
    )
    available_balance = forms.DecimalField(
        max_digits=MAX_DIGITS, decimal_places=DECIMAL_PLACES, required=False
    )

    def save(self, commit: bool = True) -> BankAccount:
        _apply_extra_fields(
            self,
            ("bank", "posted_balance", "available_balance"),
        )
        return super().save(commit=commit)


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
            "recurrence_schedule",
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

    def save(self, commit: bool = True) -> Budget:
        _apply_extra_fields(self, ("bank_account",))
        return super().save(commit=commit)


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
    readonly_fields = ("id", "created_at", "modified_at")
    fields = (
        "id",
        "name",
        "routing_number",
        "default_currency",
        "created_at",
        "modified_at",
    )


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
        "id",
        "name",
        "bank",
        "account_type",
        "currency",
        "account_number",
        "owners",
        "group",
        "posted_balance",
        "available_balance",
        "unallocated_budget",
        "link_aliases",
        "last_imported_at",
        "last_posted_through",
        "created_at",
        "modified_at",
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
        kwargs["fields"] = (
            "name",
            "account_type",
            "account_number",
            "owners",
            "group",
            "link_aliases",
        )
        return super().get_form(request, obj, change=change, **kwargs)

    ####################################################################
    #
    def get_readonly_fields(
        self, request: HttpRequest, obj: BankAccount | None = None
    ) -> tuple[str, ...]:
        """
        On creation: allow setting bank, account_number, and initial
        balances. After creation: bank and balances become read-only
        (signals manage balance updates and bank is immutable), but
        account_number remains editable so it can be filled in later.
        """
        if obj is None:
            return (
                "id",
                "unallocated_budget",
                "last_imported_at",
                "last_posted_through",
                "created_at",
                "modified_at",
            )
        return (
            "id",
            "bank",
            "currency",
            "posted_balance",
            "available_balance",
            "unallocated_budget",
            "last_imported_at",
            "last_posted_through",
            "created_at",
            "modified_at",
        )

    ####################################################################
    #
    def save_model(
        self,
        request: HttpRequest,
        obj: BankAccount,
        form: BankAccountForm,
        change: bool,
    ) -> None:
        """Use the service layer on creation so the Unallocated budget is seeded."""
        if not change:
            cleaned = form.cleaned_data
            optional = {
                field: cleaned[field]
                for field in (
                    "account_number",
                    "group",
                    "link_aliases",
                    "posted_balance",
                    "available_balance",
                )
                if cleaned.get(field) is not None
            }
            account = bank_account_svc.create(
                bank=cleaned["bank"],
                name=cleaned["name"],
                account_type=cleaned["account_type"],
                owners=list(cleaned.get("owners") or []),
                **optional,
            )
            form.instance = account
            return
        super().save_model(request, obj, form, change)


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
        "id",
    )
    list_filter = ("budget_type", "funding_type", "archived", "paused")
    search_fields = ("name",)
    formfield_overrides = {
        models.DateField: {"widget": AdminDateWidget},
    }

    # Show bank_account which is normally hidden due to editable=False.
    #
    fields = (
        "id",
        "name",
        "bank_account",
        "budget_type",
        "funding_type",
        "balance",
        "funded_amount",
        "target_balance",
        "funding_amount",
        "target_date",
        "funding_schedule",
        "recurrence_schedule",
        "fillup_goal",
        "complete",
        "paused",
        "archived",
        "archived_at",
        "last_funded_on",
        "last_recurrence_on",
        "auto_spend",
        "memo",
        "image",
        "created_at",
        "modified_at",
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
            "funding_amount",
            "target_date",
            "funding_schedule",
            "recurrence_schedule",
            "fillup_goal",
            "paused",
            "auto_spend",
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
            return (
                "id",
                "funded_amount",
                "complete",
                "archived",
                "archived_at",
                "last_funded_on",
                "last_recurrence_on",
                "created_at",
                "modified_at",
            )
        return (
            "id",
            "bank_account",
            "funded_amount",
            "complete",
            "archived",
            "archived_at",
            "last_funded_on",
            "last_recurrence_on",
            "created_at",
            "modified_at",
        )

    ####################################################################
    #
    def save_model(
        self,
        request: HttpRequest,
        obj: Budget,
        form: BudgetForm,
        change: bool,
    ) -> None:
        """Use the service layer on creation so scheduling state and fill-up goals are initialized."""
        if not change:
            cleaned = form.cleaned_data
            optional = {
                field: cleaned[field]
                for field in (
                    "balance",
                    "target_date",
                    "funding_schedule",
                    "recurrence_schedule",
                    "fillup_goal",
                    "paused",
                    "memo",
                    "image",
                )
                if cleaned.get(field) is not None
            }
            budget = budget_svc.create(
                bank_account=cleaned["bank_account"],
                name=cleaned["name"],
                budget_type=cleaned["budget_type"],
                funding_type=cleaned["funding_type"],
                target_balance=cleaned["target_balance"],
                **optional,
            )
            form.instance = budget
            return
        super().save_model(request, obj, form, change)


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
        "id",
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
        "id",
        "bank_account",
        "posted_date",
        "transaction_date",
        "created_at",
        "modified_at",
        "amount",
        "transaction_type",
        "pending",
        "bank_transaction_id",
        "description",
        "raw_description",
        "party",
        "memo",
        "bank_account_posted_balance",
        "bank_account_available_balance",
        "linked_transaction",
        "image",
        "document",
    )
    readonly_fields = (
        "id",
        "amount",
        "bank_account",
        "party",
        "posted_date",
        "transaction_date",
        "created_at",
        "modified_at",
        "pending",
        "bank_transaction_id",
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
        "id",
    )
    list_filter = ("category", "budget")
    search_fields = ("memo",)
    fields = (
        "id",
        "transaction",
        "budget",
        "amount",
        "category",
        "budget_balance",
        "memo",
        "created_at",
        "modified_at",
    )
    readonly_fields = (
        "id",
        "transaction",
        "amount",
        "budget_balance",
        "created_at",
        "modified_at",
    )


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
    # Optional: backdate the transfer so it slots into the correct position
    # in the running-balance chain.  Defaults to now() in the service layer
    # when left blank.  Use this when manually reversing and recreating a
    # transfer to fix the running-balance display.
    effective_date: forms.SplitDateTimeField = forms.SplitDateTimeField(
        required=False,
        widget=AdminSplitDateTime(),
        help_text=(
            "Leave blank to use the current time. "
            "Set this to a past date/time to backdate the transfer."
        ),
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

    ####################################################################
    #
    def save(self, commit: bool = True) -> InternalTransaction:
        _apply_extra_fields(
            self, ("amount", "src_budget", "dst_budget", "effective_date")
        )
        return super().save(commit=commit)


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
        "id",
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
            return ("amount", "src_budget", "dst_budget", "effective_date")
        return (
            "id",
            "bank_account",
            "amount",
            "src_budget",
            "dst_budget",
            "actor",
            "effective_date",
            "src_budget_balance",
            "dst_budget_balance",
            "system_event_kind",
            "system_event_date",
            "created_at",
            "modified_at",
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
            "id",
            "amount",
            "bank_account",
            "src_budget",
            "dst_budget",
            "actor",
            "effective_date",
            "src_budget_balance",
            "dst_budget_balance",
            "system_event_kind",
            "system_event_date",
            "created_at",
            "modified_at",
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
        """Delegate to the service layer on creation so balances are updated."""
        if not change:
            cleaned = form.cleaned_data
            src: Budget = cleaned["src_budget"]
            amount = Money(cleaned["amount"], src.balance.currency)
            effective_date = cleaned.get("effective_date") or None
            itx_svc.create(
                bank_account=src.bank_account,
                src_budget=src,
                dst_budget=cleaned["dst_budget"],
                amount=amount,
                actor=request.user,  # type: ignore[arg-type]
                effective_date=effective_date,
            )
            # The service created and saved the row; skip super().save_model()
            return
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
