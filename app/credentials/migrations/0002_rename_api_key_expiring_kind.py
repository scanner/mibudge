# The api_key_expiring notification kind moved with its sending task
# from the users app to credentials, so its dotted kind string changed
# from "users.api_key_expiring" to "credentials.api_key_expiring".
# Kind strings are stored on Notification and NotificationPreference
# rows; rewrite the existing rows so history and preferences follow.

from django.db import migrations

OLD_KIND = "users.api_key_expiring"
NEW_KIND = "credentials.api_key_expiring"


def rename_kind(apps, schema_editor):
    """Rewrite stored kind strings to the new dotted name."""
    for model_name in ("Notification", "NotificationPreference"):
        model = apps.get_model("notifications", model_name)
        model.objects.filter(kind=OLD_KIND).update(kind=NEW_KIND)


def unrename_kind(apps, schema_editor):
    """Restore the old dotted kind name."""
    for model_name in ("Notification", "NotificationPreference"):
        model = apps.get_model("notifications", model_name)
        model.objects.filter(kind=NEW_KIND).update(kind=OLD_KIND)


class Migration(migrations.Migration):

    dependencies = [
        ("credentials", "0001_initial"),
        ("notifications", "0005_channelpreference_default_daily_morning"),
    ]

    operations = [
        migrations.RunPython(rename_kind, unrename_kind),
    ]
