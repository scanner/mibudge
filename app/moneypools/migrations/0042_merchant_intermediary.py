# Add Transaction.merchant_intermediary and the MerchantIntermediaryPattern
# lookup table, then seed it with the payment-platform prefixes found in
# real BofA card descriptors (2026-07 survey of CSV statements + the dev
# database, both no longer on disk -- see
# app/moneypools/service/merchant_enrichment.py for how these patterns are
# applied).
#
# `pattern` is matched case-insensitively, anchored at the start of
# raw_description; the optional named group 'store' captures the text
# following the platform's prefix (further cleaned up by the service
# before use). `order` is explicit here because migration RunPython
# operates on a historical model with no custom save() -- the real
# django-ordered-model auto-assignment only applies to app code.

import uuid

from django.db import migrations, models

PATTERNS: list[dict[str, object]] = [
    {
        "order": 0,
        "token": "square",
        "display_name": "Square",
        "pattern": r"^SQ\s*\*\s*(?P<store>.+)$",
    },
    {
        "order": 1,
        "token": "toast",
        "display_name": "Toast",
        "pattern": r"^TST\*\s*(?P<store>.+)$",
    },
    {
        "order": 2,
        "token": "spoton",
        "display_name": "SpotOn",
        "pattern": r"^SPO\s*\*\s*(?P<store>.+)$",
    },
    {
        "order": 3,
        "token": "par",
        "display_name": "PAR",
        "pattern": r"^PAR\*\s*(?P<store>.+)$",
    },
    {
        "order": 4,
        "token": "olo",
        "display_name": "Olo",
        "pattern": r"^OLO\*\s*(?P<store>.+)$",
    },
    {
        "order": 5,
        "token": "grubhub",
        "display_name": "Grubhub",
        "pattern": r"^GRUBHUB\*\s*(?P<store>.+)$",
    },
    {
        "order": 6,
        "token": "doordash",
        "display_name": "DoorDash",
        # BofA's DoorDash descriptor is "DD *DOORDASH <fragment>" -- the
        # fragment is frequently truncated mid-word (e.g. "LITTLEMAD");
        # captured as-is rather than guessed at.
        "pattern": r"^DD\s*\*DOORDASH\s+(?P<store>.+)$",
    },
    {
        "order": 7,
        "token": "actblue",
        "display_name": "ActBlue",
        # Political/cause donation processor -- structurally identical
        # to the marketplace patterns above (front for a recipient org
        # rather than a store).
        "pattern": r"^ACTBLUE\*\s*(?P<store>.+)$",
    },
]


def seed_patterns(apps, schema_editor):
    """Create the reviewed intermediary patterns if not already present."""
    MerchantIntermediaryPattern = apps.get_model(
        "moneypools", "MerchantIntermediaryPattern"
    )
    existing = set(
        MerchantIntermediaryPattern.objects.values_list("token", flat=True)
    )
    MerchantIntermediaryPattern.objects.bulk_create(
        MerchantIntermediaryPattern(**entry)
        for entry in PATTERNS
        if entry["token"] not in existing
    )


def unseed_patterns(apps, schema_editor):
    """Delete the seeded rows (rows added later via admin are untouched)."""
    MerchantIntermediaryPattern = apps.get_model(
        "moneypools", "MerchantIntermediaryPattern"
    )
    seeded_tokens = {entry["token"] for entry in PATTERNS}
    MerchantIntermediaryPattern.objects.filter(
        token__in=seeded_tokens
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("moneypools", "0041_transaction_merchant_details"),
    ]

    operations = [
        migrations.CreateModel(
            name="MerchantIntermediaryPattern",
            fields=[
                (
                    "order",
                    models.PositiveIntegerField(
                        db_index=True, editable=False, verbose_name="order"
                    ),
                ),
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
                    "pattern",
                    models.CharField(
                        help_text=(
                            "Case-insensitive regex matched against the "
                            "transaction's raw_description. An optional "
                            "named group 'store' captures the text "
                            "following the platform's prefix."
                        ),
                        max_length=200,
                    ),
                ),
                (
                    "token",
                    models.CharField(
                        help_text=(
                            "Stable slug stored in "
                            "Transaction.merchant_intermediary "
                            "(e.g. 'square')."
                        ),
                        max_length=32,
                        unique=True,
                    ),
                ),
                (
                    "display_name",
                    models.CharField(
                        help_text=(
                            "Human-readable platform name used in the "
                            "composed description (e.g. 'Square')."
                        ),
                        max_length=64,
                    ),
                ),
                ("active", models.BooleanField(default=True)),
            ],
            options={
                "verbose_name_plural": "merchant intermediary patterns",
                "ordering": ("order",),
                "abstract": False,
            },
        ),
        migrations.AddField(
            model_name="transaction",
            name="merchant_intermediary",
            field=models.CharField(
                blank=True,
                db_index=True,
                editable=False,
                max_length=32,
                null=True,
            ),
        ),
        migrations.RunPython(seed_patterns, unseed_patterns),
    ]
