from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("moneypools", "0025_internaltransaction_effective_date"),
    ]

    operations = [
        migrations.RenameField(
            model_name="budget",
            old_name="recurrance_schedule",
            new_name="recurrence_schedule",
        ),
    ]
