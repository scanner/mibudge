# Elidable: re-derives transaction_date from the embedded MM/DD pattern in
# raw_description + posted_date for rows where they are still identical
# (i.e. rows that pre-date the backfill management command).
#
# On a fresh database all rows pass through here; on a production database
# that has already had ``manage.py backfill_transaction_dates`` applied this
# RunPython is a fast no-op (the filter matches zero rows).  It is safe to
# squash or elide this migration once all environments have been migrated.

import re
from datetime import UTC, datetime

from django.db import migrations, models


_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})\b")


def _parse_transaction_date(raw_description, posted_date, max_days_before=7):
    """Inline copy of description_utils.parse_transaction_date.

    Inlined to keep the migration self-contained and immune to future
    changes in the live utility.
    """
    m = _RE.search(raw_description)
    if not m:
        return posted_date
    try:
        month, day = int(m.group(1)), int(m.group(2))
        candidate = posted_date.replace(month=month, day=day)
    except ValueError:
        return posted_date
    if candidate > posted_date:
        try:
            candidate = candidate.replace(year=posted_date.year - 1)
        except ValueError:
            return posted_date
    delta = (posted_date - candidate).days
    if 0 <= delta <= max_days_before:
        return candidate
    return posted_date


def rederive_transaction_dates(apps, schema_editor):
    """Re-derive transaction_date where it still equals posted_date."""
    Transaction = apps.get_model("moneypools", "Transaction")

    qs = Transaction.objects.filter(
        transaction_date=models.F("posted_date")
    ).exclude(posted_date__isnull=True)

    to_update = []
    for tx in qs.iterator(chunk_size=500):
        posted = tx.posted_date.astimezone(UTC).date()
        derived = _parse_transaction_date(tx.raw_description, posted)
        if derived != posted:
            tx.transaction_date = datetime(
                derived.year, derived.month, derived.day, tzinfo=UTC
            )
            to_update.append(tx)
        if len(to_update) >= 500:
            Transaction.objects.bulk_update(to_update, ["transaction_date"])
            to_update.clear()

    if to_update:
        Transaction.objects.bulk_update(to_update, ["transaction_date"])


class Migration(migrations.Migration):

    dependencies = [
        ("moneypools", "0020_add_transaction_posted_date"),
    ]

    operations = [
        migrations.RunPython(
            rederive_transaction_dates,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
