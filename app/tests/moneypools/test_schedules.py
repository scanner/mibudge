#!/usr/bin/env python
#
"""
Tests for the pure recurrence-schedule helpers in
moneypools/service/schedules.py.

These helpers do no database access, so no django_db mark is needed.
"""

# system imports
#
from datetime import UTC, date, datetime

# 3rd party imports
#
import pytest
import recurrence

# Project imports
#
from moneypools.service.schedules import (
    count_occurrences,
    normalize_dtstart,
    rules_fingerprint,
)


####################################################################
#
def _semi_monthly(dtstart: datetime | None = None) -> recurrence.Recurrence:
    """Return a fresh 15th/last-day schedule (normalize mutates in place)."""
    return recurrence.Recurrence(
        dtstart=dtstart,
        rrules=[recurrence.Rule(recurrence.MONTHLY, bymonthday=[15, -1])],
    )


####################################################################
#
def _bare_monthly(dtstart: datetime | None = None) -> recurrence.Recurrence:
    """Return a fresh bare FREQ=MONTHLY schedule (fire day from DTSTART)."""
    return recurrence.Recurrence(
        dtstart=dtstart,
        rrules=[recurrence.Rule(recurrence.MONTHLY)],
    )


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


########################################################################
########################################################################
#
class TestNormalizeDtstart:
    """Tests for anchoring a schedule's DTSTART on a real occurrence."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "sched,anchor,expected",
        [
            # Bare RRULE, anchor between fire days: snap forward to the
            # next real occurrence (not the anchor itself, which the
            # rule does not fire on).
            (
                _semi_monthly(),
                date(2026, 5, 19),
                datetime(2026, 5, 31, tzinfo=UTC),
            ),
            # Anchor lands exactly on a fire day: keep it.
            (
                _semi_monthly(),
                date(2026, 5, 15),
                datetime(2026, 5, 15, tzinfo=UTC),
            ),
            # Bare FREQ=MONTHLY has no fire day without an anchor; the
            # anchor itself defines it and is the first occurrence.
            (
                _bare_monthly(),
                date(2026, 5, 19),
                datetime(2026, 5, 19, tzinfo=UTC),
            ),
            # Existing DTSTART is kept as the rule anchor (fire day 19)
            # while the stored DTSTART moves forward past the new
            # anchor date.
            (
                _bare_monthly(dtstart=datetime(2026, 5, 19)),
                date(2026, 7, 20),
                datetime(2026, 8, 19, tzinfo=UTC),
            ),
            # Existing DTSTART on a semi-monthly rule: pattern comes
            # from BYMONTHDAY, anchor just moves forward.
            (
                _semi_monthly(dtstart=datetime(2026, 1, 15)),
                date(2026, 7, 16),
                datetime(2026, 7, 31, tzinfo=UTC),
            ),
        ],
    )
    def test_anchors_on_first_real_occurrence(
        self,
        sched: recurrence.Recurrence,
        anchor: date,
        expected: datetime,
    ) -> None:
        """
        GIVEN: a funding schedule (bare or already anchored) and an
               anchor date
        WHEN:  normalize_dtstart is called
        THEN:  DTSTART is set to the first date the rule genuinely fires
               on/after the anchor, preserving the rule's fire pattern,
               and the include_dtstart flag (disabled internally during
               the search) is restored
        """
        result = normalize_dtstart(sched, anchor)

        assert result is sched
        assert result.dtstart == expected
        assert result.include_dtstart is True

    ####################################################################
    #
    @pytest.mark.parametrize(
        "sched",
        [
            # No schedule at all.
            None,
            # A schedule without recurrence rules.
            recurrence.Recurrence(),
            # A rule that never fires on/after the anchor (UNTIL in the
            # past): DTSTART must not point at a date the rule does not
            # fire on.
            recurrence.Recurrence(
                rrules=[
                    recurrence.Rule(
                        recurrence.MONTHLY, until=datetime(2020, 1, 1)
                    )
                ],
            ),
        ],
    )
    def test_left_unchanged_when_nothing_to_anchor(
        self,
        sched: recurrence.Recurrence | None,
    ) -> None:
        """
        GIVEN: no schedule, a rule-less schedule, or a rule with no
               occurrence on/after the anchor
        WHEN:  normalize_dtstart is called
        THEN:  the input is returned unchanged with DTSTART left unset
        """
        result = normalize_dtstart(sched, date(2026, 1, 1))

        assert result is sched
        if sched is not None:
            assert sched.dtstart is None


########################################################################
########################################################################
#
class TestRulesFingerprint:
    """Tests for the DTSTART-insensitive schedule comparison."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "sched_a,sched_b,expect_equal",
        [
            # A client echoing the stored pattern without its anchor is
            # not a pattern change.
            (_semi_monthly(), _semi_monthly(datetime(2026, 1, 15)), True),
            # Different recurrence patterns must differ.
            (_semi_monthly(), _bare_monthly(), False),
            # Null and rule-less schedules fingerprint alike (empty).
            (None, recurrence.Recurrence(), True),
        ],
    )
    def test_fingerprint_equality(
        self,
        sched_a: recurrence.Recurrence | None,
        sched_b: recurrence.Recurrence | None,
        expect_equal: bool,
    ) -> None:
        """
        GIVEN: two schedules
        WHEN:  both are fingerprinted
        THEN:  fingerprints match exactly when the recurrence patterns
               match, ignoring the DTSTART anchor
        """
        equal = rules_fingerprint(sched_a) == rules_fingerprint(sched_b)
        assert equal is expect_equal
