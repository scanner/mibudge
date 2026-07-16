# Create the TransactionCategory and TransactionCategoryAlias models.
#
# First of the six-step conversion of TransactionCategory from a
# TextChoices enum to a shared model (0037-0042):
#   0037 create the models (this file)
#   0038 seed the 150 global category rows
#   0039 add TransactionAllocation.category_ref FK
#   0040 data-migrate the old allocation CharField values onto the FK
#   0041 drop the CharField, rename category_ref -> category
#   0042 add Transaction.category FK, backfill from single-allocation
#        transactions, canonicalize Budget.auto_spend entries
#
# Also updates Budget.auto_spend's help_text (documentation only).

import uuid

import django.db.models.deletion
import django.db.models.functions.text
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("moneypools", "0036_anchor_funding_schedule_dtstart"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="budget",
            name="auto_spend",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="List of matcher strings; currently transaction-category full names ('{group} : {name}').  Spend matching an entry is auto-routed to this budget.",
            ),
        ),
        migrations.CreateModel(
            name="TransactionCategory",
            fields=[
                (
                    "pkid",
                    models.BigAutoField(
                        editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, unique=True
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("modified_at", models.DateTimeField(auto_now=True)),
                ("group", models.CharField(max_length=64)),
                ("name", models.CharField(max_length=64)),
                (
                    "archived",
                    models.BooleanField(
                        default=False,
                        help_text="Archived categories are hidden from pickers but remain valid on existing transactions and allocations.",
                    ),
                ),
                (
                    "owner",
                    models.ForeignKey(
                        blank=True,
                        default=None,
                        help_text="NULL for a global category shared by all users.",
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="transaction_categories",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name_plural": "transaction categories",
                "ordering": ["group", "name"],
            },
        ),
        migrations.CreateModel(
            name="TransactionCategoryAlias",
            fields=[
                (
                    "pkid",
                    models.BigAutoField(
                        editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, unique=True
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("modified_at", models.DateTimeField(auto_now=True)),
                (
                    "provider",
                    models.CharField(
                        help_text='Source of the raw category string (e.g. "bofa").',
                        max_length=32,
                    ),
                ),
                (
                    "alias_key",
                    models.CharField(
                        help_text='Normalized provider category ("group:name", casefolded, whitespace collapsed).',
                        max_length=140,
                    ),
                ),
                (
                    "category",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="aliases",
                        to="moneypools.transactioncategory",
                        to_field="id",
                    ),
                ),
            ],
            options={
                "verbose_name_plural": "transaction category aliases",
            },
        ),
        migrations.AddConstraint(
            model_name="transactioncategory",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower("group"),
                django.db.models.functions.text.Lower("name"),
                condition=models.Q(("owner__isnull", True)),
                name="transaction_category_unique_global",
            ),
        ),
        migrations.AddConstraint(
            model_name="transactioncategory",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower("group"),
                django.db.models.functions.text.Lower("name"),
                models.F("owner"),
                condition=models.Q(("owner__isnull", False)),
                name="transaction_category_unique_per_owner",
            ),
        ),
        migrations.AddConstraint(
            model_name="transactioncategoryalias",
            constraint=models.UniqueConstraint(
                fields=("provider", "alias_key"),
                name="transaction_category_alias_unique_per_provider",
            ),
        ),
    ]
