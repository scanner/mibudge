"""
Pure recurrence-schedule helpers.

No database access.  All functions operate only on
recurrence.Recurrence objects and plain date/datetime values.
"""

# system imports
#
import logging
from datetime import date, datetime, timedelta

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

    return max(1, len(occurrences))
