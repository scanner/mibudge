# Add Transaction.category, backfill it from single-allocation
# transactions, and canonicalize Budget.auto_spend entries.
#
# Backfill: a transaction with exactly one allocation gets that
# allocation's category (the common non-split case).  Split
# transactions keep NULL -- their per-portion categories live on the
# allocations.
#
# auto_spend: entries were enum strings ('Food & Drink:Groceries');
# they become canonical full names ('Food & Drink : Groceries')
# matched case-insensitively against the seeded rows, with the same
# enum-spelling translation 0039 applies to allocations.  Sentinel
# entries ('Uncategorized:Unassigned') are dropped.

import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Count

SENTINEL_KEY = ("uncategorized", "unassigned")

# Enum values whose canonical seeded row is spelled differently.  Keys
# are casefolded normalized (group, name) pairs; values are the
# canonical seeded pair.
ENUM_SPELLING_CHANGES: dict[tuple[str, str], tuple[str, str]] = {
    ("food & drink", "alcohol & bars"): ("Food & Drink", "Alcohol"),
    ("transportation", "taxies"): ("Transportation", "Taxis & Rideshare"),
}


def _normalize(raw):
    """Split on the first colon; strip and collapse whitespace.

    Mirrors moneypools.service.categories.normalize_category, inlined
    because migrations must not import application code.
    """
    group, sep, name = raw.partition(":")
    group = " ".join(group.split())
    if not sep:
        return group, group
    name = " ".join(name.split())
    return group, name or group


def _canonical(raw):
    """Normalize an enum string and apply the spelling changes.

    Returns (group, name, casefolded_key) for the canonical pair.
    """
    group, name = _normalize(raw)
    key = (group.casefold(), name.casefold())
    changed = ENUM_SPELLING_CHANGES.get(key)
    if changed is not None:
        group, name = changed
        key = (group.casefold(), name.casefold())
    return group, name, key


def backfill_transaction_categories(apps, schema_editor):
    """Copy the category of single-allocation transactions upward."""
    Transaction = apps.get_model("moneypools", "Transaction")
    TransactionAllocation = apps.get_model(
        "moneypools", "TransactionAllocation"
    )

    single_tx_ids = (
        TransactionAllocation.objects.values("transaction")
        .annotate(n=Count("pkid"))
        .filter(n=1)
        .values("transaction")
    )
    allocations = TransactionAllocation.objects.filter(
        transaction__in=single_tx_ids,
        category__isnull=False,
    ).values_list("transaction_id", "category_id")

    # Group by category so each category is one UPDATE statement.
    by_category = {}
    for tx_uuid, category_uuid in allocations:
        by_category.setdefault(category_uuid, []).append(tx_uuid)
    for category_uuid, tx_uuids in by_category.items():
        Transaction.objects.filter(id__in=tx_uuids).update(
            category=category_uuid
        )


def clear_transaction_categories(apps, schema_editor):
    """Reverse: the column is dropped by the AddField reverse; no-op."""


def rewrite_auto_spend(apps, schema_editor):
    """Canonicalize Budget.auto_spend entries to full-name strings."""
    Budget = apps.get_model("moneypools", "Budget")
    TransactionCategory = apps.get_model("moneypools", "TransactionCategory")

    by_key = {
        (c.group.casefold(), c.name.casefold()): c
        for c in TransactionCategory.objects.filter(owner__isnull=True)
    }

    for budget in Budget.objects.exclude(auto_spend=[]):
        entries = budget.auto_spend or []
        rewritten = []
        for entry in entries:
            if not isinstance(entry, str):
                rewritten.append(entry)
                continue
            group, name, key = _canonical(entry)
            if not group or key == SENTINEL_KEY:
                continue  # drop sentinel / empty entries
            category = by_key.get(key)
            if category is not None:
                rewritten.append(f"{category.group} : {category.name}")
            else:
                rewritten.append(f"{group} : {name}")
        if rewritten != entries:
            Budget.objects.filter(pk=budget.pk).update(auto_spend=rewritten)


def unrewrite_auto_spend(apps, schema_editor):
    """Reverse: write entries back in the old colon-joined enum form."""
    Budget = apps.get_model("moneypools", "Budget")
    for budget in Budget.objects.exclude(auto_spend=[]):
        entries = budget.auto_spend or []
        rewritten = []
        for entry in entries:
            if not isinstance(entry, str):
                rewritten.append(entry)
                continue
            group, name = _normalize(entry)
            rewritten.append(f"{group}:{name}")
        if rewritten != entries:
            Budget.objects.filter(pk=budget.pk).update(auto_spend=rewritten)


class Migration(migrations.Migration):
    dependencies = [
        ("moneypools", "0039_convert_allocation_category"),
    ]

    operations = [
        migrations.AddField(
            model_name="transaction",
            name="category",
            field=models.ForeignKey(
                blank=True,
                default=None,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="transactions",
                to="moneypools.transactioncategory",
                to_field="id",
            ),
        ),
        migrations.RunPython(
            backfill_transaction_categories, clear_transaction_categories
        ),
        migrations.RunPython(rewrite_auto_spend, unrewrite_auto_spend),
    ]
