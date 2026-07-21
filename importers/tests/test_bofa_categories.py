#!/usr/bin/env python
#
"""Tests for the BofA category -> mibudge category translation."""

# system imports
from pathlib import Path

# 3rd party imports
import pytest

# Project imports
from importers.bofa_categories import (
    category_for,
    category_key,
    load_overlay_map,
)


########################################################################
########################################################################
#
class TestCategoryKey:
    """Tests for provider-string key normalization."""

    ################################################################
    #
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Groceries : Groceries", "groceries:groceries"),
            ("  Home &   Utilities: Utilities ", "home & utilities:utilities"),
            # No colon -> single-level, group == name.
            ("Travel", "travel:travel"),
        ],
    )
    def test_key_normalization(self, raw: str, expected: str) -> None:
        """
        GIVEN: a provider category string
        WHEN:  reduced to a map key
        THEN:  it is split, whitespace-collapsed, and casefolded
        """
        assert category_key(raw) == expected


########################################################################
########################################################################
#
class TestCategoryFor:
    """Tests for the per-transaction category lookup."""

    ################################################################
    #
    @pytest.mark.parametrize(
        "raw,overlay,expected_name,expected_known",
        [
            # Built-in hit (input arrives in BofA's display form).
            ("Groceries : Groceries", None, "Food & Drink : Groceries", True),
            # Vocabulary miss: no category AND flagged for the run
            # report.
            ("Brand New : Bucket", None, None, False),
            # Empty category string is normal (not every transaction
            # has one) -- no category, not a miss.
            ("", None, None, True),
            # Overlay wins over the built-in map.
            (
                "Groceries : Groceries",
                {"groceries:groceries": "Personal : Hobbies"},
                "Personal : Hobbies",
                True,
            ),
            # Overlay maps a new string.
            (
                "Brand New : Bucket",
                {"brand new:bucket": "Personal : Hobbies"},
                "Personal : Hobbies",
                True,
            ),
            # Overlay null = deliberately unassigned (known, no name).
            (
                "Groceries : Groceries",
                {"groceries:groceries": None},
                None,
                True,
            ),
        ],
    )
    def test_lookup(
        self,
        raw: str,
        overlay: dict[str, str | None] | None,
        expected_name: str | None,
        expected_known: bool,
    ) -> None:
        """
        GIVEN: a provider category string and an optional overlay
        WHEN:  it is translated
        THEN:  the overlay wins over the built-ins, misses are flagged,
               and null mappings mean deliberately unassigned
        """
        lookup = category_for(raw, overlay)
        assert lookup.full_name == expected_name
        assert lookup.known is expected_known


########################################################################
########################################################################
#
class TestLoadOverlayMap:
    """Tests for the overlay-file loader."""

    ################################################################
    #
    def test_loads_and_normalizes_keys(self, tmp_path: Path) -> None:
        """
        GIVEN: an overlay file with denormalized keys and a null value
        WHEN:  it is loaded
        THEN:  keys are normalized and null survives as None
        """
        path = tmp_path / "overlay.yaml"
        path.write_text(
            "'Shopping & Entertainment : Sporting Goods': "
            "'Sports & Fitness : Sporting Goods'\n"
            "'weird new:thing': null\n",
            encoding="utf-8",
        )
        overlay = load_overlay_map(path)
        assert overlay == {
            "shopping & entertainment:sporting goods": (
                "Sports & Fitness : Sporting Goods"
            ),
            "weird new:thing": None,
        }

    ################################################################
    #
    @pytest.mark.parametrize(
        "content",
        [
            # Not a mapping at all.
            "- just\n- a\n- list\n",
            # Non-string value.
            "'groceries:groceries': 42\n",
        ],
    )
    def test_malformed_files_are_rejected(
        self, tmp_path: Path, content: str
    ) -> None:
        """
        GIVEN: an overlay file that is not a flat string mapping
        WHEN:  it is loaded
        THEN:  a ValueError names the file
        """
        path = tmp_path / "overlay.yaml"
        path.write_text(content, encoding="utf-8")
        with pytest.raises(ValueError, match="overlay.yaml"):
            load_overlay_map(path)
