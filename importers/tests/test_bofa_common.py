#!/usr/bin/env python
#
"""Tests for the shared BofA scraping primitives (bofa_common)."""

# system imports
from dataclasses import dataclass, field
from typing import Any

# 3rd party imports
import pytest

# Project imports
from importers import bofa_common
from importers.bofa_common import (
    DetailsPacer,
    fetch_details_for_account,
    merchant_signature,
    synthesize_merchant_copy,
)


########################################################################
########################################################################
#
@dataclass
class FakeTxn:
    """Stand-in for a bofa_scraper transaction object."""

    date: str
    desc: str
    amount: float
    has_details: bool = True


########################################################################
########################################################################
#
@dataclass
class FakeSession:
    """Stand-in ScrapeSession serving canned details dicts.

    `responses` maps a transaction desc to the details dict to return;
    a missing key returns None (a failed fetch).  Every dialog open is
    recorded in `opened`.
    """

    responses: dict[str, dict[str, Any]] = field(default_factory=dict)
    opened: list[str] = field(default_factory=list)

    def get_transaction_details(self, txn: FakeTxn) -> dict[str, Any] | None:
        self.opened.append(txn.desc)
        return self.responses.get(txn.desc)

    def dismiss_dialog(self) -> None:
        pass


########################################################################
########################################################################
#
@dataclass
class FakeAccount:
    """Stand-in bofa_scraper Account."""

    txns: list[FakeTxn] = field(default_factory=list)

    def get_transactions(self) -> list[FakeTxn]:
        return self.txns


####################################################################
#
def _pacer(limit: int) -> DetailsPacer:
    """A pacer with all sleeping disabled for tests."""
    return DetailsPacer(limit=limit, delay=0, batch_size=0)


####################################################################
#
def _details(name: str) -> dict[str, Any]:
    """A minimal BofA-shaped details dict for merchant `name`."""
    return {
        "merchant_name": name,
        "transaction_category": "Dining : Restaurants",
        "virtual_card_number": f"XXXX-{name[-4:]}",
    }


########################################################################
########################################################################
#
class TestMerchantSignature:
    """Tests for the merchant signature reduction."""

    ################################################################
    #
    @pytest.mark.parametrize(
        "left,right,same",
        [
            # Dates, store numbers, and card digits vary per visit;
            # the signature must not.
            (
                "COSTCO WHSE #123 05/17 PURCHASE SPRINGFIELD IL",
                "COSTCO WHSE #987 06/02 PURCHASE SPRINGFIELD IL",
                True,
            ),
            # Different city -> different signature (city survives).
            (
                "COSTCO WHSE PURCHASE SPRINGFIELD IL",
                "COSTCO WHSE PURCHASE PEORIA IL",
                False,
            ),
            ("", "ANY", False),
        ],
    )
    def test_signature_stability(
        self, left: str, right: str, same: bool
    ) -> None:
        """
        GIVEN: two activity-row descriptions
        WHEN:  reduced to merchant signatures
        THEN:  visit-specific digits collapse but merchants/cities
               stay distinct
        """
        assert (merchant_signature(left) == merchant_signature(right)) is same


########################################################################
########################################################################
#
class TestSynthesizeMerchantCopy:
    """Tests for merchant-copy payload synthesis."""

    ################################################################
    #
    def test_copy_strips_per_transaction_data_and_stamps_provenance(
        self,
    ) -> None:
        """
        GIVEN: a fetched details dict (already stamped details_source)
        WHEN:  a merchant copy is synthesized from it
        THEN:  virtual_card_number is dropped and provenance points at
               the source transaction
        """
        fetched = _details("Trader Joes")
        fetched["details_source"] = "bofa"

        copy = synthesize_merchant_copy(fetched, "src-uuid")

        assert copy["merchant_name"] == "Trader Joes"
        assert copy["transaction_category"] == "Dining : Restaurants"
        assert "virtual_card_number" not in copy
        assert copy["details_source"] == "merchant-copy"
        assert copy["copied_from"] == "src-uuid"
        # The source dict is not mutated.
        assert fetched["details_source"] == "bofa"


########################################################################
########################################################################
#
class TestFetchDetailsForAccount:
    """Tests for the budgeted merchant-copy fetch loop."""

    ################################################################
    #
    def test_budget_truncates_and_leaves_rest_for_next_run(self) -> None:
        """
        GIVEN: three distinct merchants and a budget of two opens
        WHEN:  the fetch loop runs
        THEN:  two are fetched, the third is skipped for the next run
        """
        txns = [
            FakeTxn("07/15/2026", f"MERCHANT {c} PURCHASE TOWN XX", -10.0)
            for c in ("AAA", "BBB", "CCC")
        ]
        session = FakeSession(
            responses={t.desc: _details(t.desc[:12]) for t in txns}
        )
        pacer = _pacer(limit=2)

        results, stats = fetch_details_for_account(
            session,
            FakeAccount(txns),
            [(f"uuid-{i}", t) for i, t in enumerate(txns)],
            pacer,
            {},
            load_more=0,
        )

        assert stats.fetched == 2
        assert stats.skipped_budget == 1
        assert len(results) == 2
        assert pacer.used == 2
        assert session.opened == [txns[0].desc, txns[1].desc]

    ################################################################
    #
    def test_merchant_copy_is_free_and_survives_budget_exhaustion(
        self,
    ) -> None:
        """
        GIVEN: one merchant appearing three times and a budget of one
        WHEN:  the fetch loop runs
        THEN:  one dialog open serves all three rows -- the copies are
               synthesized even after the budget is exhausted
        """
        desc = "COSTCO WHSE #123 PURCHASE SPRINGFIELD IL"
        txns = [
            FakeTxn("07/15/2026", desc, -10.0),
            FakeTxn(
                "07/10/2026", "COSTCO WHSE #987 PURCHASE SPRINGFIELD IL", -20.0
            ),
            FakeTxn("07/05/2026", desc, -30.0),
        ]
        session = FakeSession(
            responses={t.desc: _details("Costco") for t in txns}
        )
        seen: dict[str, Any] = {}

        results, stats = fetch_details_for_account(
            session,
            FakeAccount(txns),
            [(f"uuid-{i}", t) for i, t in enumerate(txns)],
            _pacer(limit=1),
            seen,
            load_more=0,
        )

        assert stats.fetched == 1
        assert stats.copied == 2
        assert stats.skipped_budget == 0
        assert len(session.opened) == 1

        fetched, copies = results[0], results[1:]
        assert fetched["details"]["details_source"] == "bofa"
        for copy in copies:
            assert copy["details"]["details_source"] == "merchant-copy"
            assert copy["details"]["copied_from"] == "uuid-0"
            assert "virtual_card_number" not in copy["details"]

    ################################################################
    #
    def test_copy_repeats_disabled_fetches_every_row(self) -> None:
        """
        GIVEN: a repeated merchant and copy_repeats=False (offline
               capture mode)
        WHEN:  the fetch loop runs with an unlimited budget
        THEN:  every row's real dialog is opened
        """
        desc = "COSTCO WHSE PURCHASE SPRINGFIELD IL"
        txns = [FakeTxn("07/15/2026", desc, -10.0) for _ in range(2)]
        session = FakeSession(responses={desc: _details("Costco")})

        results, stats = fetch_details_for_account(
            session,
            FakeAccount(txns),
            [(f"uuid-{i}", t) for i, t in enumerate(txns)],
            _pacer(limit=-1),
            {},
            load_more=0,
            copy_repeats=False,
        )

        assert stats.fetched == 2
        assert stats.copied == 0
        assert len(session.opened) == 2

    ################################################################
    #
    def test_rows_without_details_and_failures_are_counted(self) -> None:
        """
        GIVEN: a row without a details dialog and a row whose fetch
               fails
        WHEN:  the fetch loop runs
        THEN:  each is counted, no result is produced for either, and
               the failure still consumes budget (it opened a dialog)
        """
        no_details = FakeTxn(
            "07/15/2026", "CHECK DEPOSIT", 100.0, has_details=False
        )
        failing = FakeTxn("07/14/2026", "FLAKY MERCHANT TOWN XX", -5.0)
        session = FakeSession(responses={})  # every open returns None
        pacer = _pacer(limit=5)

        results, stats = fetch_details_for_account(
            session,
            FakeAccount([no_details, failing]),
            [("uuid-0", no_details), ("uuid-1", failing)],
            pacer,
            {},
            load_more=0,
            wedge_threshold=0,
        )

        assert results == []
        assert stats.skipped_no_details == 1
        assert stats.failed == 1
        assert pacer.used == 1


########################################################################
########################################################################
#
class TestDetailsPacer:
    """Tests for the run-wide dialog-open budget."""

    ################################################################
    #
    @pytest.mark.parametrize(
        "limit,used,exhausted",
        [
            (30, 0, False),
            (30, 30, True),
            # 0 = fetching disabled: always exhausted.
            (0, 0, True),
            # Negative = unlimited (--details-all captures).
            (-1, 10_000, False),
        ],
    )
    def test_exhausted(self, limit: int, used: int, exhausted: bool) -> None:
        """
        GIVEN: a pacer with a limit and a usage count
        WHEN:  exhausted is checked
        THEN:  the budget semantics (0 disabled, negative unlimited)
               hold
        """
        assert DetailsPacer(limit=limit, used=used).exhausted is exhausted


########################################################################
########################################################################
#
class TestWebDriverExceptionFallback:
    """The selenium exception stand-in keeps the module importable."""

    ################################################################
    #
    def test_fetch_failure_via_exception(self) -> None:
        """
        GIVEN: a session whose dialog open raises WebDriverException
        WHEN:  the fetch loop runs
        THEN:  the row is counted failed rather than crashing the run
        """

        class RaisingSession(FakeSession):
            def get_transaction_details(
                self, txn: FakeTxn
            ) -> dict[str, Any] | None:
                raise bofa_common.WebDriverException("boom")

        txn = FakeTxn("07/15/2026", "SOME MERCHANT TOWN XX", -5.0)
        results, stats = fetch_details_for_account(
            RaisingSession(),
            FakeAccount([txn]),
            [("uuid-0", txn)],
            _pacer(limit=5),
            {},
            load_more=0,
            wedge_threshold=0,
        )

        assert results == []
        assert stats.failed == 1
