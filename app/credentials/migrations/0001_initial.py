# APIKey moved here from the users app (created there by users/0008 +
# users/0009).  The CreateModel is state-only, declaring db_table
# "users_apikey" so it points at the existing table; the AlterModelTable
# that follows then really renames the table to this app's default name
# ("credentials_apikey") and drops the db_table override from state.
# No data is copied and no rows change.

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("users", "0010_move_apikey_to_credentials"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="APIKey",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        (
                            "uuid",
                            models.UUIDField(
                                default=uuid.uuid4,
                                editable=False,
                                unique=True,
                            ),
                        ),
                        (
                            "name",
                            models.CharField(
                                help_text=(
                                    "User-supplied label identifying what "
                                    "this key is for."
                                ),
                                max_length=100,
                            ),
                        ),
                        (
                            "prefix",
                            models.CharField(editable=False, max_length=12),
                        ),
                        (
                            "hashed_key",
                            models.CharField(
                                editable=False, max_length=64, unique=True
                            ),
                        ),
                        ("expires_at", models.DateTimeField(blank=True, null=True)),
                        (
                            "last_used_at",
                            models.DateTimeField(blank=True, null=True),
                        ),
                        (
                            "expiry_notified_at",
                            models.DateTimeField(blank=True, null=True),
                        ),
                        ("revoked_at", models.DateTimeField(blank=True, null=True)),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("modified_at", models.DateTimeField(auto_now=True)),
                        (
                            "user",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="api_keys",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "API key",
                        "ordering": ["-created_at"],
                        "db_table": "users_apikey",
                    },
                ),
            ],
            database_operations=[],
        ),
        # Real DB operation: rename users_apikey to the app-default
        # credentials_apikey (table=None resets to the default name and
        # clears the db_table option from state).
        migrations.AlterModelTable(name="apikey", table=None),
    ]
