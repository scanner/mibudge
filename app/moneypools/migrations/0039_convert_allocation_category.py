# Convert TransactionAllocation.category from the old TextChoices
# enum CharField to a TransactionCategory FK.
#
# Three steps in one change: add the FK (as category_ref), translate
# the stored enum strings onto seeded rows, then drop the CharField
# and rename category_ref -> category.
#
# Translation rules: enum values are 'Group:Name' strings.
# Normalization (split on the FIRST colon, strip, collapse whitespace,
# case-insensitive match) absorbs stored typo variants like
# 'Education: Tuition & Fees'.  ENUM_SPELLING_CHANGES covers the enum
# values whose canonical seeded row is spelled differently.  The
# legacy 'Uncategorized:Unassigned' sentinel becomes NULL -- NULL
# means unassigned.  Any value that still has no seeded match
# (unexpected) gets a global row created so no data is dropped.

import django.db.models.deletion
from django.db import migrations, models

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
        group, name, key = _canonical(raw)
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
        ("moneypools", "0038_seed_global_categories"),
    ]

    operations = [
        migrations.AddField(
            model_name="transactionallocation",
            name="category_ref",
            field=models.ForeignKey(
                blank=True,
                default=None,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="allocations",
                to="moneypools.transactioncategory",
                to_field="id",
            ),
        ),
        migrations.RunPython(migrate_categories, unmigrate_categories),
        migrations.RemoveField(
            model_name="transactionallocation",
            name="category",
        ),
        migrations.RenameField(
            model_name="transactionallocation",
            old_name="category_ref",
            new_name="category",
        ),
    ]
