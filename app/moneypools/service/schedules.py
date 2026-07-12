"""
Pure recurrence-schedule helpers.

No database access.  All functions operate only on
recurrence.Recurrence objects and plain date/datetime values.
"""

# system imports
#
import logging
from datetime import UTC, date, datetime, timedelta

# 3rd party imports
#
import recurrence as recurrence_lib

logger = logging.getLogger(__name__)


####################################################################
#
def enumerate_schedule(
    sched: recurrence_lib.Recurrence | None,
    after: date,
    before: date,
) -> list[date]:
    """Return all dates on sched in (after, before].

    Args:
        sched: A recurrence.Recurrence object, or None.
        after: Exclusive lower bound (last processed date).
        before: Inclusive upper bound (today).

    Returns:
        Sorted list of dates strictly after *after* and <= *before*.
    """
    if not sched:
        return []

    # The recurrence library uses naive datetimes internally; passing
    # timezone-aware datetimes causes a TypeError on the internal comparison.
    after_dt = datetime(after.year, after.month, after.day)
    before_dt = datetime(before.year, before.month, before.day, 23, 59, 59)

    # Use the schedule's stored dtstart if present; fall back to after_dt so
    # the rule fires on the same day-of-month as the last-processed date rather
    # than defaulting to datetime.now() (which is non-deterministic).
    # Strip timezone: the stored dtstart comes back as UTC-aware after DB
    # round-trip, but the recurrence library uses naive datetimes internally.
    raw = sched.dtstart
    dtstart = raw.replace(tzinfo=None) if raw is not None else after_dt

    try:
        occurrences = list(
            sched.between(after_dt, before_dt, inc=False, dtstart=dtstart)
        )
    except (recurrence_lib.RecurrenceError, TypeError, ValueError) as exc:
        logger.warning("enumerate_schedule: recurrence error: %r", exc)
        return []

    results = []
    for occ in occurrences:
        d = occ.date() if hasattr(occ, "date") else occ
        if after < d <= before:
            results.append(d)

    return sorted(set(results))


####################################################################
#
def prev_recurrence_boundary(
    sched: recurrence_lib.Recurrence | None,
    as_of: date,
) -> date | None:
    """Return the most recent occurrence of sched on or before as_of.

    Used to find the start of the current recurrence cycle for fill-up goals.

    Args:
        sched: The recurrence schedule.
        as_of: Date to search up to (inclusive).

    Returns:
        Most recent occurrence date, or None if none found within 2 years.
    """
    if not sched:
        return None

    start_dt = datetime(as_of.year - 2, as_of.month, as_of.day)
    end_dt = datetime(as_of.year, as_of.month, as_of.day, 23, 59, 59)

    raw = sched.dtstart
    dtstart = raw.replace(tzinfo=None) if raw is not None else start_dt

    try:
        occurrences = list(
            sched.between(start_dt, end_dt, inc=True, dtstart=dtstart)
        )
        if not occurrences:
            return None
        last = occurrences[-1]
        return (
            last.date()
            if hasattr(last, "date")
            else date(last.year, last.month, last.day)
        )
    except (recurrence_lib.RecurrenceError, TypeError, ValueError) as exc:
        logger.warning("prev_recurrence_boundary: recurrence error: %r", exc)
        return None


####################################################################
#
def next_recurrence_boundary(
    sched: recurrence_lib.Recurrence | None,
    from_date: date,
) -> date | None:
    """Return the first date the recurrence schedule fires on or after from_date.

    Used to find the next cycle-reset boundary for RECURRING budgets, so
    gap-spreading is capped at the upcoming reset rather than an arbitrary date.

    Args:
        sched: The recurrence schedule (e.g. monthly-on-the-1st).
        from_date: Lower bound (inclusive).

    Returns:
        Next occurrence date, or None if none found within 2 years.
    """
    if not sched:
        return None

    # Search up to 2 years out; subtract one day so from_date itself is
    # included (between() is exclusive on the lower bound).
    start_dt = datetime(
        from_date.year, from_date.month, from_date.day
    ) - timedelta(days=1)
    look_ahead = date(from_date.year + 2, from_date.month, from_date.day)
    end_dt = datetime(
        look_ahead.year, look_ahead.month, look_ahead.day, 23, 59, 59
    )

    raw = sched.dtstart
    dtstart = raw.replace(tzinfo=None) if raw is not None else start_dt

    try:
        occurrences = sched.between(start_dt, end_dt, inc=True, dtstart=dtstart)
        first = next(iter(occurrences), None)
        if first is None:
            return None
        return (
            first.date()
            if hasattr(first, "date")
            else date(first.year, first.month, first.day)
        )
    except (recurrence_lib.RecurrenceError, TypeError, ValueError) as exc:
        logger.warning("next_recurrence_boundary: recurrence error: %r", exc)
        return None


####################################################################
#
def count_occurrences(
    sched: recurrence_lib.Recurrence | None,
    from_date: date,
    end_date: date,
) -> int:
    """Count occurrences of a schedule from from_date (inclusive) to end_date.

    Used for TARGET_DATE gap-spreading: divide remaining gap by this count.

    Args:
        sched: The funding schedule.
        from_date: Start date (inclusive).
        end_date: Upper bound (inclusive); pass budget.target_date for Goals.

    Returns:
        Number of occurrences in [from_date, end_date] (minimum 1).
    """
    if not sched:
        return 1

    # between() is exclusive on the lower bound; subtract one day so
    # from_date itself is included.  Use naive datetimes (library requirement).
    start_dt = datetime(
        from_date.year, from_date.month, from_date.day
    ) - timedelta(days=1)
    end_dt = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59)

    raw = sched.dtstart
    dtstart = raw.replace(tzinfo=None) if raw is not None else start_dt

    try:
        occurrences = list(
            sched.between(start_dt, end_dt, inc=True, dtstart=dtstart)
        )
    except (recurrence_lib.RecurrenceError, TypeError, ValueError) as exc:
        logger.warning("count_occurrences: recurrence error: %r", exc)
        return 1

    # Post-filter to [from_date, end_date].  between() returns dates in
    # [start_dt, end_dt] (inc=True), which is one day too wide on the
    # lower bound; worse, when the schedule has no stored DTSTART the
    # fallback dtstart (start_dt) is itself emitted as an occurrence
    # (django-recurrence include_dtstart), inflating the count by one
    # and shrinking every per-event deposit.
    results = set()
    for occ in occurrences:
        d = (
            occ.date()
            if hasattr(occ, "date")
            else date(occ.year, occ.month, occ.day)
        )
        if from_date <= d <= end_date:
            results.add(d)

    return max(1, len(results))


####################################################################
#
def normalize_dtstart(
    sched: recurrence_lib.Recurrence | None,
    anchor: date,
) -> recurrence_lib.Recurrence | None:
    """Anchor sched's DTSTART at its first real occurrence on/after anchor.

    django-recurrence treats DTSTART itself as an occurrence (an implicit
    RDATE via include_dtstart, which does not survive serialization
    round-trips and so cannot simply be disabled on the stored value).
    A DTSTART on a day the rule does not fire therefore becomes a
    persisted phantom funding event.  This helper avoids that by setting
    DTSTART to a date the rule genuinely fires on.

    The rule pattern is preserved: when sched already has a DTSTART it is
    kept as the rule anchor (a bare FREQ=MONTHLY rule takes its
    day-of-month from it), and only the stored DTSTART moves forward to
    the first occurrence on/after *anchor*.  When sched has no DTSTART,
    *anchor* itself anchors the rule.

    Args:
        sched: The schedule to normalize (mutated in place), or None.
        anchor: Earliest date the new DTSTART may fall on -- budget
            creation date on create, the edit date on re-anchoring
            updates.

    Returns:
        The same Recurrence instance with DTSTART set to a real
        occurrence, or the input unchanged when there is nothing to
        normalize (no schedule, no rules, or no occurrence found).
    """
    if not sched or not sched.rrules:
        return sched

    anchor_dt = datetime(anchor.year, anchor.month, anchor.day)
    raw = sched.dtstart
    rule_anchor = raw.replace(tzinfo=None) if raw is not None else anchor_dt

    # Look far enough ahead for sparse rules (e.g. yearly).
    look_ahead = datetime(anchor.year + 5, anchor.month, anchor.day)

    # Temporarily disable include_dtstart so the rule anchor is not
    # emitted as a synthetic occurrence on a day the rule does not fire.
    saved_include = sched.include_dtstart
    sched.include_dtstart = False
    try:
        occurrences = sched.between(
            anchor_dt - timedelta(days=1),
            look_ahead,
            inc=True,
            dtstart=rule_anchor,
        )
    except (recurrence_lib.RecurrenceError, TypeError, ValueError) as exc:
        logger.warning("normalize_dtstart: recurrence error: %r", exc)
        return sched
    finally:
        sched.include_dtstart = saved_include

    for occ in occurrences:
        d = (
            occ.date()
            if hasattr(occ, "date")
            else date(occ.year, occ.month, occ.day)
        )
        if d >= anchor:
            # Store as UTC midnight (serialized 'T000000Z'): a naive
            # datetime would be treated as local time on serialization,
            # shifting the calendar date in timezones east of UTC.
            sched.dtstart = datetime(d.year, d.month, d.day, tzinfo=UTC)
            return sched

    logger.warning(
        "normalize_dtstart: no occurrence on/after %s within %s years; "
        "leaving DTSTART unchanged",
        anchor,
        5,
    )
    return sched


####################################################################
#
def rules_fingerprint(sched: recurrence_lib.Recurrence | None) -> str:
    """Return a comparable serialization of sched ignoring its DTSTART.

    Used to decide whether an incoming schedule actually changes the
    recurrence pattern (RRULE/EXRULE/RDATE/EXDATE parts) or merely
    round-trips the stored one without its DTSTART anchor -- SPA clients
    send bare RRULEs, so a field-level comparison would always differ.

    Args:
        sched: The schedule to fingerprint, or None.

    Returns:
        The serialized schedule with DTSTART/DTEND lines removed; empty
        string for a null/empty schedule.
    """
    if not sched:
        return ""
    lines = recurrence_lib.serialize(sched).splitlines()
    return "\n".join(
        line for line in lines if not line.startswith(("DTSTART", "DTEND"))
    )
