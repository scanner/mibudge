"""
Django-filter FilterSets for the moneypools API.

Each FilterSet defines the query parameters accepted on list endpoints.
Filters operate on the already-ownership-scoped queryset returned by
``AccountOwnerQuerySetMixin.get_queryset()``, so no additional
permission checks are needed here.
"""

# 3rd party imports
from django_filters import rest_framework as filters

# Project imports
from moneypools.models import (
    Budget,
    InternalTransaction,
    Transaction,
    TransactionAllocation,
)


########################################################################
########################################################################
#
class BudgetFilter(filters.FilterSet):
    """Filter budgets by bank account, type, and state."""

    bank_account = filters.UUIDFilter(field_name="bank_account__id")
    budget_type = filters.ChoiceFilter(
        choices=Budget.BudgetType.choices,
    )
    archived = filters.BooleanFilter()
    paused = filters.BooleanFilter()

    class Meta:
        model = Budget
        fields = [
            "bank_account",
            "budget_type",
            "archived",
            "paused",
        ]


########################################################################
########################################################################
#
class TransactionFilter(filters.FilterSet):
    """Filter transactions by bank account, date range, status, and type."""

    bank_account = filters.UUIDFilter(field_name="bank_account__id")
    pending = filters.BooleanFilter()
    transaction_type = filters.ChoiceFilter(
        choices=Transaction.TransactionType.choices,
    )
    date_from = filters.DateTimeFilter(
        field_name="transaction_date",
        lookup_expr="gte",
    )
    date_to = filters.DateTimeFilter(
        field_name="transaction_date",
        lookup_expr="lte",
    )
    posted_date_from = filters.DateTimeFilter(
        field_name="posted_date",
        lookup_expr="gte",
    )
    posted_date_to = filters.DateTimeFilter(
        field_name="posted_date",
        lookup_expr="lte",
    )

    class Meta:
        model = Transaction
        fields = [
            "bank_account",
            "pending",
            "transaction_type",
            "date_from",
            "date_to",
            "posted_date_from",
            "posted_date_to",
        ]


########################################################################
########################################################################
#
class TransactionAllocationFilter(filters.FilterSet):
    """Filter allocations by bank account, transaction, budget, and category."""

    bank_account = filters.UUIDFilter(
        field_name="transaction__bank_account__id",
    )
    transaction = filters.UUIDFilter(field_name="transaction__id")
    budget = filters.UUIDFilter(field_name="budget__id")
    category = filters.CharFilter()

    class Meta:
        model = TransactionAllocation
        fields = [
            "bank_account",
            "transaction",
            "budget",
            "category",
        ]


########################################################################
########################################################################
#
class InternalTransactionFilter(filters.FilterSet):
    """Filter internal transactions by bank account and budgets."""

    bank_account = filters.UUIDFilter(field_name="bank_account__id")
    src_budget = filters.UUIDFilter(field_name="src_budget__id")
    dst_budget = filters.UUIDFilter(field_name="dst_budget__id")
    date_from = filters.DateTimeFilter(
        field_name="created_at",
        lookup_expr="gte",
    )
    date_to = filters.DateTimeFilter(
        field_name="created_at",
        lookup_expr="lte",
    )

    class Meta:
        model = InternalTransaction
        fields = [
            "bank_account",
            "src_budget",
            "dst_budget",
            "date_from",
            "date_to",
        ]
