# Seed the Paddle payment-platform prefix as a MerchantIntermediaryPattern.
#
# Paddle is a merchant-of-record for software vendors: the card descriptor
# fronts the real product behind a "PADDLE.NET*" soft descriptor (observed
# in real BofA card data, e.g. "PADDLE.NET* TOWER 06/25 PURCHASE PADDLE.COM
# NY", where the store is "TOWER").  Structurally identical to the
# marketplace prefixes seeded in 0042; see
# app/moneypools/service/merchant_enrichment.py for how patterns are applied.
#
# Additive and idempotent: only creates the row if its token is absent, so
# it is safe alongside admin-created rows.

from django.db import migrations

PATTERNS: list[dict[str, object]] = [
    {
        "order": 8,
        "token": "paddle",
        "display_name": "Paddle",
        "pattern": r"^PADDLE\.NET\*\s*(?P<store>.+)$",
    },
]


def seed_patterns(apps, schema_editor):
    """Create the Paddle pattern if not already present."""
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
        ("moneypools", "0042_merchant_intermediary"),
    ]

    operations = [
        migrations.RunPython(seed_patterns, unseed_patterns),
    ]
