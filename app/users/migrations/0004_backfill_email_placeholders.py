# system imports
#
from django.db import migrations


def backfill_email(apps, schema_editor):
    """
    Assign placeholder emails to users who have a blank email so that the
    subsequent unique-email constraint can be added safely.

    funding-system → funding-system@invalid.local (recognizable sentinel)
    all others     → {username}@invalid.local
    """
    User = apps.get_model("users", "User")
    for user in User.objects.filter(email=""):
        user.email = f"{user.username}@invalid.local"
        user.save(update_fields=["email"])


def reverse_backfill_email(apps, schema_editor):
    """Blank out the @invalid.local placeholders we inserted."""
    User = apps.get_model("users", "User")
    User.objects.filter(email__endswith="@invalid.local").update(email="")


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0003_user_timezone"),
        # Must run after the funding-system seed so we backfill its blank email.
        ("moneypools", "0024_seed_funding_system_user"),
    ]

    operations = [
        migrations.RunPython(
            backfill_email,
            reverse_code=reverse_backfill_email,
        ),
    ]
