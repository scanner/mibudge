#!/usr/bin/env python
#
"""Tests for moneypools.description_utils."""

# system imports
#
import json
from datetime import date
from pathlib import Path

# 3rd party imports
#
import pytest

# Project imports
#
from moneypools.description_utils import parse_transaction_date

_FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "transaction_descriptions.json"
)
_TX_FIXTURE: list[dict] = json.loads(_FIXTURE_PATH.read_text())


########################################################################
########################################################################
#
class TestParseTransactionDate:
    """Tests for parse_transaction_date."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "raw_description,posted,expected",
        [
            # Date present, within window.
            (
                "TST*CAFE BORRONE 03/28 MOBILE PURCHASE",
                date(2026, 3, 31),
                date(2026, 3, 28),
            ),
            # Date at boundary (same day as posted).
            (
                "SOME VENDOR 04/01 PURCHASE",
                date(2026, 4, 1),
                date(2026, 4, 1),
            ),
            # Date exactly 7 days before (at the edge of the window).
            (
                "SOME VENDOR 03/25 PURCHASE",
                date(2026, 4, 1),
                date(2026, 3, 25),
            ),
            # Date 8 days before -- outside window, falls back to posted.
            (
                "SOME VENDOR 03/24 PURCHASE",
                date(2026, 4, 1),
                date(2026, 4, 1),
            ),
            # No date in description -- falls back to posted.
            (
                "ACH DIRECT DEPOSIT PAYROLL",
                date(2026, 4, 1),
                date(2026, 4, 1),
            ),
            # January wrap-around: purchase in Dec, posted in Jan.
            (
                "VENDOR 12/30 MOBILE PURCHASE",
                date(2026, 1, 2),
                date(2025, 12, 30),
            ),
            # Candidate in same year would be in the future -- resolved to prior year.
            (
                "VENDOR 12/31 MOBILE PURCHASE",
                date(2026, 1, 1),
                date(2025, 12, 31),
            ),
            # Single-digit month and day parsed correctly.
            (
                "VENDOR 3/5 PURCHASE",
                date(2026, 3, 7),
                date(2026, 3, 5),
            ),
        ],
    )
    def test_parse_transaction_date(
        self,
        raw_description: str,
        posted: date,
        expected: date,
    ) -> None:
        """
        GIVEN: a raw bank description and a posted date
        WHEN:  parse_transaction_date is called
        THEN:  the correct purchase date is returned
        """
        assert parse_transaction_date(raw_description, posted) == expected

    ####################################################################
    #
    def test_custom_max_days_before(self) -> None:
        """
        GIVEN: a description with a date 10 days before posted
        WHEN:  parse_transaction_date is called with max_days_before=10
        THEN:  the parsed date is returned instead of the fallback
        """
        raw = "VENDOR 03/22 PURCHASE"
        posted = date(2026, 4, 1)
        assert parse_transaction_date(raw, posted, max_days_before=10) == date(
            2026, 3, 22
        )

    ####################################################################
    #
    def test_invalid_month_day_falls_back(self) -> None:
        """
        GIVEN: a description containing an invalid date like 13/45
        WHEN:  parse_transaction_date is called
        THEN:  the fallback posted_date is returned
        """
        raw = "VENDOR 13/45 PURCHASE"
        posted = date(2026, 4, 1)
        assert parse_transaction_date(raw, posted) == posted


########################################################################
########################################################################
#
class TestParseTransactionDateFixture:
    """Fixture-driven tests using anonymised real bank descriptions."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "entry",
        _TX_FIXTURE,
        ids=[e["description"][:60] for e in _TX_FIXTURE],
    )
    def test_real_descriptions(self, entry: dict) -> None:
        """
        GIVEN: a real (anonymised) bank description and its posted date
        WHEN:  parse_transaction_date is called
        THEN:  the expected purchase date is returned
        """
        posted = date.fromisoformat(entry["posted_date"])
        expected = date.fromisoformat(entry["expected_date"])
        assert parse_transaction_date(entry["description"], posted) == expected
