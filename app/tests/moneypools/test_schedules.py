#!/usr/bin/env python
#
"""
Tests for the pure recurrence-schedule helpers in
moneypools/service/schedules.py.

These helpers do no database access, so no django_db mark is needed.
"""

# system imports
#
from datetime import date, datetime

# 3rd party imports
#
import pytest
import recurrence

# Project imports
#
from moneypools.service.schedules import count_occurrences

# Fires on the 15th and last day of each month, anchored at Jan 15.
_SEMI_MONTHLY = recurrence.Recurrence(
    dtstart=datetime(2026, 1, 15),
    rrules=[recurrence.Rule(recurrence.MONTHLY, bymonthday=[15, -1])],
)

# The same rule with no DTSTART -- this is what the SPA's schedule picker
# produces (a bare RRULE).  Regression shape for the phantom-occurrence
# fencepost: count_occurrences falls back to from_date - 1 day as the
# dtstart anchor, and django-recurrence (include_dtstart=True) emits that
# synthetic anchor as an occurrence, inflating the count by one.
_SEMI_MONTHLY_NO_DTSTART = recurrence.Recurrence(
    rrules=[recurrence.Rule(recurrence.MONTHLY, bymonthday=[15, -1])],
)

# Fires on the 1st of each month.
_MONTHLY = recurrence.Recurrence(
    dtstart=datetime(2026, 1, 1),
    rrules=[recurrence.Rule(recurrence.MONTHLY)],
)


########################################################################
########################################################################
#
class TestCountOccurrences:
    """Tests for count_occurrences window and fencepost behavior."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "sched,from_date,end_date,expected",
        [
            # Regression from a real goal budget: two events (Jul 15,
            # Jul 31) remain before an Aug 1 target.  With no stored
            # DTSTART the synthetic anchor on Jul 14 must not be counted.
            (
                _SEMI_MONTHLY_NO_DTSTART,
                date(2026, 7, 15),
                date(2026, 8, 1),
                2,
            ),
            # Same window with a stored DTSTART outside the window.
            (_SEMI_MONTHLY, date(2026, 7, 15), date(2026, 8, 1), 2),
            # A real occurrence exactly one day before from_date (Jul 15)
            # must not be counted: only Jul 31 is in [Jul 16, Aug 1].
            (_SEMI_MONTHLY, date(2026, 7, 16), date(2026, 8, 1), 1),
            # from_date itself is an occurrence and is included.
            (_SEMI_MONTHLY, date(2026, 7, 31), date(2026, 8, 1), 1),
            # end_date itself is an occurrence and is included.
            (_SEMI_MONTHLY, date(2026, 7, 15), date(2026, 7, 31), 2),
            # Monthly over three month boundaries.
            (_MONTHLY, date(2026, 1, 1), date(2026, 3, 1), 3),
            # No DTSTART, monthly-on-day rule spanning several months.
            (
                _SEMI_MONTHLY_NO_DTSTART,
                date(2026, 5, 31),
                date(2026, 8, 1),
                5,
            ),
        ],
    )
    def test_counts_only_occurrences_within_window(
        self,
        sched: recurrence.Recurrence,
        from_date: date,
        end_date: date,
        expected: int,
    ) -> None:
        """
        GIVEN: a funding schedule and an inclusive [from_date, end_date] window
        WHEN:  count_occurrences is called
        THEN:  only real schedule occurrences inside the window are counted --
               no phantom synthetic-dtstart occurrence, no day-before leakage
        """
        assert count_occurrences(sched, from_date, end_date) == expected

    ####################################################################
    #
    @pytest.mark.parametrize(
        "sched,from_date,end_date",
        [
            # Window past the last occurrence before end_date: floor of 1.
            (_MONTHLY, date(2026, 3, 2), date(2026, 3, 15)),
            # from_date after end_date (deadline passed): floor of 1.
            (_MONTHLY, date(2026, 6, 1), date(2026, 3, 1)),
            # No schedule at all: floor of 1.
            (None, date(2026, 1, 1), date(2026, 3, 1)),
        ],
    )
    def test_returns_floor_of_one(
        self,
        sched: recurrence.Recurrence | None,
        from_date: date,
        end_date: date,
    ) -> None:
        """
        GIVEN: a window containing no occurrences, an inverted window, or
               no schedule at all
        WHEN:  count_occurrences is called
        THEN:  returns the floor of 1 so gap division never divides by zero
        """
        assert count_occurrences(sched, from_date, end_date) == 1
