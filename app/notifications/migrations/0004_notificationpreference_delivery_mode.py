# Generated migration: replace enabled BooleanField with delivery_mode CharField.
#
# Migration steps (single file, single deploy):
#   1. Add delivery_mode as nullable so existing rows are valid pre-backfill.
#   2. Backfill: enabled=True  -> 'digest', enabled=False -> 'off'.
#   3. Make delivery_mode non-nullable with default 'digest'.
#   4. Remove the old enabled field.

from django.db import migrations, models


def _backfill_delivery_mode(apps, schema_editor):
    NotificationPreference = apps.get_model(
        "notifications", "NotificationPreference"
    )
    NotificationPreference.objects.filter(enabled=True).update(
        delivery_mode="digest"
    )
    NotificationPreference.objects.filter(enabled=False).update(
        delivery_mode="off"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0003_remove_notification_sender_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="notificationpreference",
            name="delivery_mode",
            field=models.CharField(
                max_length=20,
                null=True,
                choices=[
                    ("digest", "Digest"),
                    ("immediate", "Immediate"),
                    ("off", "Off"),
                ],
            ),
        ),
        migrations.RunPython(
            _backfill_delivery_mode,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="notificationpreference",
            name="delivery_mode",
            field=models.CharField(
                max_length=20,
                default="digest",
                choices=[
                    ("digest", "Digest"),
                    ("immediate", "Immediate"),
                    ("off", "Off"),
                ],
            ),
        ),
        migrations.RemoveField(
            model_name="notificationpreference",
            name="enabled",
        ),
    ]
