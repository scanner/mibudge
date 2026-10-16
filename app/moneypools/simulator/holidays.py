"""
Federal Reserve holidays and business days.

ACH payments, card settlement and payroll follow the Federal Reserve's
calendar: no settlement on weekends or on the eleven Fed holidays.  A
holiday that falls on a Sunday is observed the Monday after; one that
falls on a Saturday is not moved (the Fed is open the Friday before).
"""

# system imports
#
import calendar
from datetime import date, timedelta
from functools import cache


####################################################################
#
def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The `n`th `weekday` (0 = Monday) of a month; n = -1 is the last."""
    if n > 0:
        first = date(year, month, 1)
        offset = (weekday - first.weekday()) % 7
        return first + timedelta(days=offset + 7 * (n - 1))
    last = date(year, month, calendar.monthrange(year, month)[1])
    return last - timedelta(days=(last.weekday() - weekday) % 7)


####################################################################
#
@cache
def fed_holidays(year: int) -> frozenset[date]:
    """The days the Federal Reserve is closed for a holiday in `year`."""
    fixed = [
        date(year, 1, 1),  # New Year's Day
        date(year, 6, 19),  # Juneteenth
        date(year, 7, 4),  # Independence Day
        date(year, 11, 11),  # Veterans Day
        date(year, 12, 25),  # Christmas Day
    ]
    observed = {d + timedelta(days=1) if d.weekday() == 6 else d for d in fixed}
    observed |= {
        _nth_weekday(year, 1, 0, 3),  # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),  # Washington's Birthday
        _nth_weekday(year, 5, 0, -1),  # Memorial Day
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 10, 0, 2),  # Columbus Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving Day
    }
    return frozenset(d for d in observed if d.weekday() < 5)


####################################################################
#
def is_business_day(day: date) -> bool:
    """True when banks settle on `day`."""
    return day.weekday() < 5 and day not in fed_holidays(day.year)


####################################################################
#
def next_business_day(day: date) -> date:
    """`day`, or the first business day after it."""
    while not is_business_day(day):
        day += timedelta(days=1)
    return day


####################################################################
#
def previous_business_day(day: date) -> date:
    """`day`, or the last business day before it."""
    while not is_business_day(day):
        day -= timedelta(days=1)
    return day
