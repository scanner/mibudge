"""
Django-filter FilterSets for the moneypools API.

Each FilterSet defines the query parameters accepted on list endpoints.
Filters operate on the already-ownership-scoped queryset returned by
``AccountOwnerQuerySetMixin.get_queryset()``, so no additional
permission checks are needed here.
"""

# system imports
from django.db.models import Q

# 3rd party imports
from django_filters import rest_framework as filters

# Project imports
from moneypools.models import (
    Budget,
    EventKind,
    FundingEventOccurrence,
    InternalTransaction,
    Transaction,
    TransactionAllocation,
    TransactionCategory,
)


########################################################################
########################################################################
#
class TransactionCategoryFilter(filters.FilterSet):
    """Filter transaction categories by group, archived state, and scope.

    'scope' narrows the visibility-filtered queryset: 'global' (shared
    base set), 'mine' (owned by the requesting user), or 'shared'
    (owned by someone the user co-owns a bank account with, including
    grandfathered rows).
    """

    group = filters.CharFilter(lookup_expr="iexact")
    archived = filters.BooleanFilter()
    scope = filters.ChoiceFilter(
        choices=[
            ("global", "Global"),
            ("mine", "Mine"),
            ("shared", "Shared"),
        ],
        method="filter_by_scope",
    )

    def filter_by_scope(self, queryset, name, value):
        """Narrow to global, own, or other-owner (shared) categories."""
        match value:
            case "global":
                return queryset.filter(owner__isnull=True)
            case "mine":
                return queryset.filter(owner=self.request.user)
            case "shared":
                return queryset.filter(owner__isnull=False).exclude(
                    owner=self.request.user
                )
        return queryset

    class Meta:
        model = TransactionCategory
        fields = [
            "group",
            "archived",
            "scope",
        ]


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
    category = filters.UUIDFilter(field_name="category__id")
    category_group = filters.CharFilter(
        field_name="category__group",
        lookup_expr="iexact",
    )
    uncategorized = filters.BooleanFilter(
        field_name="category",
        lookup_expr="isnull",
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
            "category",
            "category_group",
            "uncategorized",
        ]


########################################################################
########################################################################
#
class TransactionAllocationFilter(filters.FilterSet):
    """Filter allocations by bank account, transaction, budget, and category.

    NOTE: 'category' changed from the old enum string to the category
    UUID when TransactionCategory became a model (breaking change);
    'category_group' and 'uncategorized' were added alongside.
    """

    bank_account = filters.UUIDFilter(
        field_name="transaction__bank_account__id",
    )
    transaction = filters.UUIDFilter(field_name="transaction__id")
    budget = filters.UUIDFilter(field_name="budget__id")
    category = filters.UUIDFilter(field_name="category__id")
    category_group = filters.CharFilter(
        field_name="category__group",
        lookup_expr="iexact",
    )
    uncategorized = filters.BooleanFilter(
        field_name="category",
        lookup_expr="isnull",
    )

    class Meta:
        model = TransactionAllocation
        fields = [
            "bank_account",
            "transaction",
            "budget",
            "category",
            "category_group",
            "uncategorized",
        ]


########################################################################
########################################################################
#
class InternalTransactionFilter(filters.FilterSet):
    """Filter internal transactions by bank account and budgets."""

    bank_account = filters.UUIDFilter(field_name="bank_account__id")
    src_budget = filters.UUIDFilter(field_name="src_budget__id")
    dst_budget = filters.UUIDFilter(field_name="dst_budget__id")
    budget = filters.UUIDFilter(method="filter_by_budget")
    date_from = filters.DateTimeFilter(
        field_name="created_at",
        lookup_expr="gte",
    )
    date_to = filters.DateTimeFilter(
        field_name="created_at",
        lookup_expr="lte",
    )

    def filter_by_budget(self, queryset, name, value):
        """Match internal transactions where the budget is on either side."""
        return queryset.filter(
            Q(src_budget__id=value) | Q(dst_budget__id=value)
        )

    class Meta:
        model = InternalTransaction
        fields = [
            "bank_account",
            "src_budget",
            "dst_budget",
            "budget",
            "date_from",
            "date_to",
        ]


########################################################################
########################################################################
#
class FundingEventOccurrenceFilter(filters.FilterSet):
    """Filter funding event occurrences by account, budget, kind, status, and date."""

    bank_account = filters.UUIDFilter(field_name="budget__bank_account__id")
    budget = filters.UUIDFilter(field_name="budget__id")
    kind = filters.ChoiceFilter(
        choices=[(k.value, k.value) for k in EventKind],
    )
    status = filters.MultipleChoiceFilter(
        choices=FundingEventOccurrence.Status.choices,
    )
    date_from = filters.DateFilter(
        field_name="scheduled_date",
        lookup_expr="gte",
    )
    date_to = filters.DateFilter(
        field_name="scheduled_date",
        lookup_expr="lte",
    )

    class Meta:
        model = FundingEventOccurrence
        fields = [
            "bank_account",
            "budget",
            "kind",
            "status",
            "date_from",
            "date_to",
        ]
