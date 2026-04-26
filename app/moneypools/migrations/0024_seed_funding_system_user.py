"""
Data migration: create the non-loginable 'funding-system' user.

This user is the actor on InternalTransaction rows created by the
automated funding engine so the FK non-null invariant holds without
requiring a real human user.
"""

from django.db import migrations


def _create_funding_system_user(apps, schema_editor):
    User = apps.get_model("users", "User")
    if not User.objects.filter(username="funding-system").exists():
        User.objects.create(
            username="funding-system",
            email="",
            is_active=False,
            is_staff=False,
            is_superuser=False,
            # Unusable password -- this account can never log in.
            password="!",
        )


def _delete_funding_system_user(apps, schema_editor):
    User = apps.get_model("users", "User")
    User.objects.filter(username="funding-system").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("moneypools", "0023_add_funding_fields"),
    ]

    operations = [
        migrations.RunPython(
            _create_funding_system_user,
            reverse_code=_delete_funding_system_user,
        ),
    ]
