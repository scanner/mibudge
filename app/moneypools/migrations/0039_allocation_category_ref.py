# Add the temporary TransactionAllocation.category_ref FK.
#
# The old 'category' CharField still exists at this point; 0040 copies
# its values onto this FK and 0041 drops the CharField and renames
# category_ref -> category.  The field definition here is the final
# one so the rename in 0041 leaves the model state matching models.py.

import django.db.models.deletion
from django.db import migrations, models


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
    ]
