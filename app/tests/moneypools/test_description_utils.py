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
        "raw_description,posted,kwargs,expected",
        [
            # Date at the near edge of the window (same day as posted).
            pytest.param(
                "SOME VENDOR 04/01 PURCHASE",
                date(2026, 4, 1),
                {},
                date(2026, 4, 1),
                id="same_day",
            ),
            # Date exactly 7 days before (the far edge of the window).
            pytest.param(
                "SOME VENDOR 03/25 PURCHASE",
                date(2026, 4, 1),
                {},
                date(2026, 3, 25),
                id="window_edge",
            ),
            # Date 8 days before -- outside window, falls back to posted.
            pytest.param(
                "SOME VENDOR 03/24 PURCHASE",
                date(2026, 4, 1),
                {},
                date(2026, 4, 1),
                id="outside_window",
            ),
            # A wider window accepts a date 10 days before.
            pytest.param(
                "VENDOR 03/22 PURCHASE",
                date(2026, 4, 1),
                {"max_days_before": 10},
                date(2026, 3, 22),
                id="custom_max_days_before",
            ),
            # No date in description -- falls back to posted.
            pytest.param(
                "ACH DIRECT DEPOSIT PAYROLL",
                date(2026, 4, 1),
                {},
                date(2026, 4, 1),
                id="no_date",
            ),
            # January wrap-around: the date would be in the future in
            # the posted year, so it resolves to the prior year.
            pytest.param(
                "VENDOR 12/30 MOBILE PURCHASE",
                date(2026, 1, 2),
                {},
                date(2025, 12, 30),
                id="january_wrap",
            ),
            # Single-digit month and day parsed correctly.
            pytest.param(
                "VENDOR 3/5 PURCHASE",
                date(2026, 3, 7),
                {},
                date(2026, 3, 5),
                id="single_digit",
            ),
            # Not a real date -- falls back to posted.
            pytest.param(
                "VENDOR 13/45 PURCHASE",
                date(2026, 4, 1),
                {},
                date(2026, 4, 1),
                id="invalid_month_day",
            ),
        ],
    )
    def test_parse_transaction_date(
        self,
        raw_description: str,
        posted: date,
        kwargs: dict[str, int],
        expected: date,
    ) -> None:
        """
        GIVEN: a raw bank description, a posted date and a window (the
               default 7 days unless the case overrides it)
        WHEN:  parse_transaction_date is called
        THEN:  the embedded purchase date is returned when it is real
               and falls within the window, else the posted date
        """
        assert (
            parse_transaction_date(raw_description, posted, **kwargs)
            == expected
        )


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
