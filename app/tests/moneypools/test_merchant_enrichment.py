#!/usr/bin/env python
#
"""Tests for merchant identity cleanup (service/merchant_enrichment)."""

# 3rd party imports
import pytest

# Project imports
from moneypools.service import merchant_enrichment as merchant_enrichment_svc

pytestmark = pytest.mark.django_db


########################################################################
########################################################################
#
class TestSplitIntermediary:
    """Tests for the payment-platform prefix detector.

    Relies on the patterns seeded by migrations 0042 and 0043 (real
    platforms observed in BofA card descriptors); merchant/store names
    below are invented, not real transaction data.
    """

    ################################################################
    #
    @pytest.mark.parametrize(
        "raw_description,details_merchant_name,expected_token,"
        "expected_display,expected_store",
        [
            # Square: BofA left the descriptor unresolved -- derive
            # the store from the capture group, noise-stripped.
            (
                "SQ *ACME COFFEE SHOP 07/11 MOBILE PURCHASE Palo Alto CA",
                "SQ *ACME COFFEE SHOP",
                "square",
                "Square",
                "ACME COFFEE SHOP",
            ),
            # Square: BofA already resolved it -- trust that verbatim
            # rather than re-deriving a (possibly worse) name.
            (
                "SQ *ACME COFFEE SHOP 07/11 MOBILE PURCHASE Palo Alto CA",
                "Acme Coffee Shop",
                "square",
                "Square",
                "Acme Coffee Shop",
            ),
            # Toast, no space after the asterisk.
            (
                "TST*GOTT'S BURGERS - PA 07/05 MOBILE PURCHASE Palo Alto CA",
                None,
                "toast",
                "Toast",
                "GOTT'S BURGERS - PA",
            ),
            # Toast, WITH a space after the asterisk.
            (
                "TST* SOUP SHOP F 05/29 MOBILE PURCHASE SAN MATEO CA",
                None,
                "toast",
                "Toast",
                "SOUP SHOP F",
            ),
            # SpotOn.
            (
                "SPO*SOME CAFE 08/15 PURCHASE 650-000-0000 CA",
                None,
                "spoton",
                "SpotOn",
                "SOME CAFE",
            ),
            # PAR (restaurant POS).
            (
                "PAR*SOME BISTRO 12/22 PURCHASE SAN JOSE CA",
                None,
                "par",
                "PAR",
                "SOME BISTRO",
            ),
            # Olo (restaurant ordering platform).
            (
                "OLO*Some Deli 12/28 MOBILE PURCHASE San Carlos CA",
                None,
                "olo",
                "Olo",
                "Some Deli",
            ),
            # Grubhub marketplace.
            (
                "GRUBHUB*TACOSHOP 06/15 PURCHASE GRUBHUB.COM NY",
                "GRUBHUB*TACOSHOP",
                "grubhub",
                "Grubhub",
                "TACOSHOP",
            ),
            # DoorDash -- the store fragment is frequently truncated
            # mid-word by the card network; captured as-is.
            (
                "DD *DOORDASH SANDWICH 06/26 PURCHASE DOORDASH.COM CA",
                "DD *DOORDASH SANDWICH",
                "doordash",
                "DoorDash",
                "SANDWICH",
            ),
            # ActBlue: structurally identical to the marketplace
            # patterns, but a donation-recipient front, not a store.
            (
                "ACTBLUE* SOMECAUSE 10/31 PURCHASE SECURE.ACTBLU MA",
                None,
                "actblue",
                "ActBlue",
                "SOMECAUSE",
            ),
            # Paddle: merchant-of-record for software vendors. BofA's
            # own merchant name keeps the "PADDLE.NET*" prefix, so it is
            # NOT provider-resolved -- the store is derived from the
            # capture group and noise-stripped ("TOWER" from real data).
            (
                "PADDLE.NET* TOWER 06/25 PURCHASE PADDLE.COM NY",
                "PADDLE.NET* TOWER",
                "paddle",
                "Paddle",
                "TOWER",
            ),
            # No known prefix -- a direct merchant using its own
            # asterisk-soft-descriptor convention (UPS, AT&T, ...);
            # not treated as an intermediary.
            (
                "UPS*1Z000000 12/09 PURCHASE 800-000-0000 GA",
                None,
                None,
                None,
                None,
            ),
            (
                "ATT* BILL PAYMENT 11/03 PURCHASE 800-000-0000 TX",
                None,
                None,
                None,
                None,
            ),
        ],
    )
    def test_pattern_table(
        self,
        raw_description: str,
        details_merchant_name: str | None,
        expected_token: str | None,
        expected_display: str | None,
        expected_store: str | None,
    ) -> None:
        """
        GIVEN: a raw card descriptor and the provider's own merchant name
        WHEN:  split_intermediary is applied
        THEN:  a known platform prefix yields (token, display, store),
               preferring an already-resolved provider name over a
               regex-derived one; an unknown prefix returns None
        """
        result = merchant_enrichment_svc.split_intermediary(
            details_merchant_name, raw_description
        )
        if expected_token is None:
            assert result is None
        else:
            assert result is not None
            assert result.token == expected_token
            assert result.display_name == expected_display
            assert result.store_name == expected_store


########################################################################
########################################################################
#
class TestRefineMerchantName:
    """Tests for extend-only DBA-name recovery."""

    ################################################################
    #
    @pytest.mark.parametrize(
        "details_name,search_text,expected",
        [
            # Extends: the noise-stripped remainder starts with and
            # exceeds the provider's truncated name.
            (
                "COSTCO",
                "COSTCO GAS #10 07/14 MOBILE PURCHASE REDWOOD CITY CA",
                "COSTCO GAS",
            ),
            # Same store number/date-stripped length as details_name --
            # NOT an extension (equal length guards against reproducing
            # the same name with different casing/whitespace as if it
            # were new information).
            (
                "COSTCO WHSE",
                "COSTCO WHSE #123 07/05 PURCHASE Palo Alto CA",
                "COSTCO WHSE",
            ),
            # Diverges entirely -- never replaces a name the remainder
            # does not start with.
            (
                "Best Buy",
                "SOME OTHER STORE 07/11 MOBILE PURCHASE CA",
                "Best Buy",
            ),
            # No details_name to extend.
            (None, "ANYTHING 07/11 MOBILE PURCHASE CA", None),
            # No usable signal in the search text.
            ("Trader Joes", "", "Trader Joes"),
        ],
    )
    def test_extension_table(
        self,
        details_name: str | None,
        search_text: str,
        expected: str | None,
    ) -> None:
        """
        GIVEN: a provider-resolved name and raw text to search for more
        WHEN:  refine_merchant_name is applied
        THEN:  the name is extended only when the noise-stripped text
               starts with it and is strictly longer
        """
        assert (
            merchant_enrichment_svc.refine_merchant_name(
                details_name, search_text
            )
            == expected
        )
