"""Django admin configuration for all moneypools models."""

# 3rd party imports
#
from django.contrib import admin
from django.http import HttpRequest

# Project imports
#
from .models import (
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
@admin.register(InternalTransaction)
class InternalTransactionAdmin(admin.ModelAdmin):
    """Read-only admin for write-once internal transactions."""

    list_display = (
        "created_at",
        "amount",
        "src_budget",
        "dst_budget",
        "actor",
        "bank_account",
    )
    list_filter = ("bank_account",)
    fields = (
        "bank_account",
        "amount",
        "src_budget",
        "dst_budget",
        "actor",
        "src_budget_balance",
        "dst_budget_balance",
    )
    readonly_fields = (
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
    def has_change_permission(
        self, request: HttpRequest, obj: InternalTransaction | None = None
    ) -> bool:
        """Write-once: no editing after creation."""
        return False
