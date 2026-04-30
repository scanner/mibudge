"""
Add InternalTransaction.effective_date.

1. Add the column as nullable.
2. Back-fill existing rows: effective_date = created_at.
3. Make the column non-nullable.
"""

# system imports
#
from django.db import migrations, models


########################################################################
########################################################################
#
def backfill_effective_date(apps, schema_editor):
    InternalTransaction = apps.get_model("moneypools", "InternalTransaction")
    InternalTransaction.objects.filter(effective_date__isnull=True).update(
        effective_date=models.F("created_at")
    )


########################################################################
########################################################################
#
class Migration(migrations.Migration):
    dependencies = [
        ("moneypools", "0024_seed_funding_system_user"),
    ]

    operations = [
        migrations.AddField(
            model_name="internaltransaction",
            name="effective_date",
            field=models.DateTimeField(null=True),
        ),
        migrations.RunPython(
            backfill_effective_date,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="internaltransaction",
            name="effective_date",
            field=models.DateTimeField(),
        ),
    ]
