# Generated migration: make User.email unique and required.
#
# The prior data migration (0004) guarantees no blank emails exist, so the
# NOT NULL / unique index can be added safely without backfill here.
#
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0004_backfill_email_placeholders"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="email",
            field=models.EmailField(
                max_length=254,
                unique=True,
                verbose_name="email address",
            ),
        ),
    ]
