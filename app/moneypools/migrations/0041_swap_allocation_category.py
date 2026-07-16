# Drop the old TransactionAllocation.category CharField and rename
# category_ref -> category, completing the enum-to-FK swap for
# allocations.

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("moneypools", "0040_migrate_allocation_categories"),
    ]

    operations = [
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
