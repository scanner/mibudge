"""
Backfill a DTSTART anchor on funding schedules that lack one.

Schedules created through the SPA are bare RRULEs.  Without a DTSTART,
every schedule helper has to invent a per-call fallback anchor, which
made bare-FREQ rules fire on window-dependent days and (before the
count_occurrences fix) produced phantom funding events.  Going forward
the budget service anchors DTSTART at creation/edit time; this
migration anchors existing rows at their first real rule occurrence
on/after the budget's creation date.

The normalization logic is inlined (not imported from the service
layer) so this migration stays self-contained as the app evolves.
"""

# system imports
from datetime import UTC, datetime, timedelta

# 3rd party imports
import recurrence as recurrence_lib
from django.db import migrations


####################################################################
#
def _first_occurrence_on_or_after(sched, anchor_date):
    """Return the first real rule occurrence on/after anchor_date, or None.

    Temporarily disables include_dtstart so the search anchor is not
    itself emitted as a synthetic occurrence on a day the rule does not
    fire.
    """
    anchor_dt = datetime(
        anchor_date.year, anchor_date.month, anchor_date.day
    )
    look_ahead = datetime(
        anchor_date.year + 5, anchor_date.month, anchor_date.day
    )
    saved_include = sched.include_dtstart
    sched.include_dtstart = False
    try:
        occurrences = sched.between(
            anchor_dt - timedelta(days=1),
            look_ahead,
            inc=True,
            dtstart=anchor_dt,
        )
    except (recurrence_lib.RecurrenceError, TypeError, ValueError):
        return None
    finally:
        sched.include_dtstart = saved_include

    for occ in occurrences:
        d = occ.date() if hasattr(occ, "date") else occ
        if d >= anchor_date:
            # UTC midnight: a naive datetime would be treated as local
            # time on serialization, shifting the date east of UTC.
            return datetime(d.year, d.month, d.day, tzinfo=UTC)
    return None


####################################################################
#
def anchor_funding_schedules(apps, schema_editor):
    """Set DTSTART on funding schedules that have none."""
    Budget = apps.get_model("moneypools", "Budget")
    for budget in Budget.objects.exclude(funding_schedule="").iterator():
        sched = budget.funding_schedule
        if not sched or not sched.rrules or sched.dtstart is not None:
            continue
        dtstart = _first_occurrence_on_or_after(
            sched, budget.created_at.date()
        )
        if dtstart is None:
            continue
        sched.dtstart = dtstart
        budget.funding_schedule = sched
        budget.save(update_fields=["funding_schedule"])


class Migration(migrations.Migration):
    dependencies = [
        ("moneypools", "0035_remove_bankaccount_group"),
    ]

    operations = [
        migrations.RunPython(
            anchor_funding_schedules,
            # Reverse is a no-op: removing anchors would reintroduce the
            # ambiguity this migration exists to eliminate.
            migrations.RunPython.noop,
        ),
    ]
