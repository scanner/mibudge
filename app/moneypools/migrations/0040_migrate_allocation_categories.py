# Copy the old TransactionAllocation.category CharField values onto
# the new category_ref FK.
#
# The old values are enum strings like 'Food & Drink:Groceries'.
# Normalization (split on FIRST colon, strip, collapse whitespace,
# case-insensitive match) maps stored typo variants like
# 'Education: Tuition & Fees' onto the fixed seeded row.  The
# 'Uncategorized:Unassigned' sentinel becomes NULL -- NULL now means
# unassigned.  Any value that still has no seeded match (unexpected)
# gets a global row created so no data is dropped.

from django.db import migrations

SENTINEL_KEY = ("uncategorized", "unassigned")


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


def migrate_categories(apps, schema_editor):
    """Populate category_ref from the old CharField values."""
    TransactionCategory = apps.get_model("moneypools", "TransactionCategory")
    TransactionAllocation = apps.get_model(
        "moneypools", "TransactionAllocation"
    )

    by_key = {
        (c.group.casefold(), c.name.casefold()): c
        for c in TransactionCategory.objects.filter(owner__isnull=True)
    }

    raw_values = (
        TransactionAllocation.objects.exclude(category="")
        .values_list("category", flat=True)
        .distinct()
    )
    for raw in raw_values:
        group, name = _normalize(raw)
        key = (group.casefold(), name.casefold())
        if not group or key == SENTINEL_KEY:
            continue  # stays NULL: unassigned
        category = by_key.get(key)
        if category is None:
            category = TransactionCategory.objects.create(
                group=group, name=name, owner=None
            )
            by_key[key] = category
        TransactionAllocation.objects.filter(category=raw).update(
            category_ref=category
        )


def unmigrate_categories(apps, schema_editor):
    """Write category_ref back into the old CharField enum format."""
    TransactionAllocation = apps.get_model(
        "moneypools", "TransactionAllocation"
    )
    allocations = TransactionAllocation.objects.select_related(
        "category_ref"
    ).all()
    for allocation in allocations.iterator():
        if allocation.category_ref is None:
            value = "Uncategorized:Unassigned"
        else:
            ref = allocation.category_ref
            value = f"{ref.group}:{ref.name}"
        if allocation.category != value:
            TransactionAllocation.objects.filter(pk=allocation.pk).update(
                category=value
            )


class Migration(migrations.Migration):
    dependencies = [
        ("moneypools", "0039_allocation_category_ref"),
    ]

    operations = [
        migrations.RunPython(migrate_categories, unmigrate_categories),
    ]
