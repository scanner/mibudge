from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("moneypools", "0021_rederive_transaction_dates"),
    ]

    operations = [
        migrations.AlterField(
            model_name="transaction",
            name="posted_date",
            field=models.DateTimeField(editable=False),
        ),
    ]
