#!/usr/bin/env python
#
"""
Tests for the scrape-sync service.

Covers the scenarios that motivated the rewrite: pending descriptions
that change between scrapes, pending->posted with amount or description
changes that the old matcher could not bridge, same-date insert
ordering, snapshot recompute after older-than-existing inserts, and
the two validation paths (aggregate balance and posting-order chain).
"""

# system imports
#
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

# 3rd party imports
#
import pytest
from djmoney.money import Money

# Project imports
#
from moneypools.models import BankAccount, Budget, Transaction
from moneypools.service import sync_scrape as sync_scrape_svc
from users.models import User

pytestmark = pytest.mark.django_db


########################################################################
########################################################################
#
def _stx(
    *,
    pending: bool,
    posted_date: datetime,
    raw_description: str,
    amount: Decimal,
    transaction_type: str = "purchase",
    running_balance: Decimal | None = None,
) -> sync_scrape_svc.ScrapedTransaction:
    """Build a ScrapedTransaction with the conventions used in these tests."""
    return sync_scrape_svc.ScrapedTransaction(
        is_pending=pending,
        posted_date=posted_date,
        raw_description=raw_description,
        amount=Money(amount, "USD"),
        transaction_type=transaction_type,
        running_balance=running_balance,
    )


########################################################################
####################################################################
#
def _payload(
    *,
    ending_balance: Decimal,
    transactions: list[sync_scrape_svc.ScrapedTransaction],
    scraped_at: datetime | None = None,
) -> sync_scrape_svc.ScrapeSyncPayload:
    """Build a ScrapeSyncPayload with USD defaults."""
    return sync_scrape_svc.ScrapeSyncPayload(
        scraped_at=scraped_at or datetime(2026, 5, 19, 12, 0, tzinfo=UTC),
        ending_balance=Money(ending_balance, "USD"),
        transactions=transactions,
    )


########################################################################
####################################################################
#
@pytest.fixture
def empty_account(
    bank_account_factory: Callable[..., BankAccount],
    user_factory: Callable[..., User],
) -> BankAccount:
    """A BankAccount with zero balance and one owner."""
    user = user_factory()
    return bank_account_factory(
        owners=[user],
        currency="USD",
        available_balance=Money(0, "USD"),
        posted_balance=Money(0, "USD"),
    )


########################################################################
########################################################################
#
class TestSyncScrape:
    """End-to-end tests for `sync_scrape`."""

    ####################################################################
    #
    def test_first_sync_empty_account(self, empty_account: BankAccount) -> None:
        """
        GIVEN: an empty account
        WHEN:  sync_scrape is called with two posted and one pending row
        THEN:  the rows are inserted, available_balance matches the
               scrape's ending_balance, last_posted_through advances to
               the latest posted_date, and the report reflects the work.
        """
        # Posted: -50, -25 (settled 5/18, total -75)
        # Pending: -10 (settled "today")
        # Ending available balance: -85
        payload = _payload(
            ending_balance=Decimal("-85.00"),
            transactions=[
                _stx(
                    pending=True,
                    posted_date=datetime(2026, 5, 19, 12, 0, tzinfo=UTC),
                    raw_description="PURCHASE PENDING THING",
                    amount=Decimal("-10.00"),
                ),
                _stx(
                    pending=False,
                    posted_date=datetime(2026, 5, 18, 0, 0, tzinfo=UTC),
                    raw_description="POSTED THING B",
                    amount=Decimal("-25.00"),
                ),
                _stx(
                    pending=False,
                    posted_date=datetime(2026, 5, 18, 0, 0, tzinfo=UTC),
                    raw_description="POSTED THING A",
                    amount=Decimal("-50.00"),
                ),
            ],
        )

        report = sync_scrape_svc.sync_scrape(empty_account, payload)

        assert report.deleted_pending == 0
        assert report.inserted_posted == 2
        assert report.skipped_posted == 0
        assert report.inserted_pending == 1
        assert report.balance_mismatch is None
        assert report.last_posted_through is not None
        assert report.last_posted_through.isoformat() == "2026-05-18"
        assert len(report.new_transaction_ids) == 3

        empty_account.refresh_from_db()
        assert empty_account.available_balance == Money(-85, "USD")
        # posted_balance excludes pending
        assert empty_account.posted_balance == Money(-75, "USD")

        # Display order `(-transaction_date, -created_at)` must reproduce
        # the scrape's top-to-bottom order, because the service inserts
        # same-date rows in reverse-scrape order so the topmost-in-scrape
        # gets the highest `created_at`.
        rows = list(
            Transaction.objects.filter(bank_account=empty_account).order_by(
                "-transaction_date", "-created_at"
            )
        )
        assert [r.raw_description for r in rows] == [
            "PURCHASE PENDING THING",
            "POSTED THING B",
            "POSTED THING A",
        ]
        # Snapshots are the running balance after this row, walked
        # newest-first from the current account totals.  Pending tx
        # itself shows the current posted_balance (-75) because it has
        # not yet posted.
        assert rows[0].bank_account_available_balance == Money(-85, "USD")
        assert rows[0].bank_account_posted_balance == Money(-75, "USD")
        assert rows[1].bank_account_available_balance == Money(-75, "USD")
        assert rows[1].bank_account_posted_balance == Money(-75, "USD")
        assert rows[2].bank_account_available_balance == Money(-50, "USD")
        assert rows[2].bank_account_posted_balance == Money(-50, "USD")

    ####################################################################
    #
    def test_resync_is_idempotent_for_posted_dedupes_pending_reinserts(
        self, empty_account: BankAccount
    ) -> None:
        """
        GIVEN: the same scrape applied twice in a row
        WHEN:  the second sync_scrape runs against the just-synced state
        THEN:  posted rows are skipped (dedup), pending rows are deleted
               and re-inserted, and the final state matches the first run.
        """
        payload = _payload(
            ending_balance=Decimal("-35.00"),
            transactions=[
                _stx(
                    pending=True,
                    posted_date=datetime(2026, 5, 19, 12, 0, tzinfo=UTC),
                    raw_description="PURCHASE PENDING",
                    amount=Decimal("-10.00"),
                ),
                _stx(
                    pending=False,
                    posted_date=datetime(2026, 5, 18, 0, 0, tzinfo=UTC),
                    raw_description="POSTED THING",
                    amount=Decimal("-25.00"),
                ),
            ],
        )
        first = sync_scrape_svc.sync_scrape(empty_account, payload)
        second = sync_scrape_svc.sync_scrape(empty_account, payload)

        assert first.inserted_posted == 1
        assert first.inserted_pending == 1
        assert second.inserted_posted == 0
        assert second.skipped_posted == 1
        assert second.deleted_pending == 1
        assert second.inserted_pending == 1

        empty_account.refresh_from_db()
        assert empty_account.available_balance == Money(-35, "USD")
        assert (
            Transaction.objects.filter(bank_account=empty_account).count() == 2
        )

    ####################################################################
    #
    def test_pending_description_changes_while_still_pending(
        self, empty_account: BankAccount
    ) -> None:
        """
        GIVEN: a pending row from a prior scrape with description A
        WHEN:  a new scrape lists the same row as pending but with
               description B
        THEN:  exactly one pending row remains in the DB; it carries the
               new description.
        """
        first = _payload(
            ending_balance=Decimal("-10.00"),
            transactions=[
                _stx(
                    pending=True,
                    posted_date=datetime(2026, 5, 19, 8, 0, tzinfo=UTC),
                    raw_description="PURCHASE 03/07 ACMECORP CO/BILL ZZ",
                    amount=Decimal("-10.00"),
                ),
            ],
        )
        sync_scrape_svc.sync_scrape(empty_account, first)

        second = _payload(
            ending_balance=Decimal("-10.00"),
            transactions=[
                _stx(
                    pending=True,
                    posted_date=datetime(2026, 5, 19, 14, 0, tzinfo=UTC),
                    raw_description="PURCHASE Acmecorp Co/bill ZZ ON 03/07",
                    amount=Decimal("-10.00"),
                ),
            ],
        )
        report = sync_scrape_svc.sync_scrape(empty_account, second)
        assert report.deleted_pending == 1
        assert report.inserted_pending == 1

        rows = list(
            Transaction.objects.filter(bank_account=empty_account, pending=True)
        )
        assert len(rows) == 1
        assert rows[0].raw_description == (
            "PURCHASE Acmecorp Co/bill ZZ ON 03/07"
        )

    ####################################################################
    #
    def test_pending_to_posted_with_amount_change(
        self, empty_account: BankAccount
    ) -> None:
        """
        GIVEN: a pending charge for $40.88 (mid-meal authorization)
        WHEN:  the next scrape lists the same merchant as posted for
               $49.06 (tip added) with no remaining pending row
        THEN:  the pending row is gone, exactly one posted row at $49.06
               exists, and the account balance reflects the final amount.
        """
        pending_only = _payload(
            ending_balance=Decimal("-40.88"),
            transactions=[
                _stx(
                    pending=True,
                    posted_date=datetime(2026, 5, 19, 8, 0, tzinfo=UTC),
                    raw_description=(
                        "MOBILE PURCHASE 05/16 ACMECORP RESTAURANT"
                    ),
                    amount=Decimal("-40.88"),
                ),
            ],
        )
        sync_scrape_svc.sync_scrape(empty_account, pending_only)

        posted_only = _payload(
            ending_balance=Decimal("-49.06"),
            transactions=[
                _stx(
                    pending=False,
                    posted_date=datetime(2026, 5, 18, 0, 0, tzinfo=UTC),
                    raw_description=(
                        "ACMECORP RESTAURANT 05/16 MOBILE PURCHASE"
                    ),
                    amount=Decimal("-49.06"),
                ),
            ],
        )
        report = sync_scrape_svc.sync_scrape(empty_account, posted_only)
        assert report.deleted_pending == 1
        assert report.inserted_posted == 1
        assert report.inserted_pending == 0
        assert report.balance_mismatch is None

        rows = list(Transaction.objects.filter(bank_account=empty_account))
        assert len(rows) == 1
        assert rows[0].pending is False
        assert rows[0].amount == Money(Decimal("-49.06"), "USD")

        empty_account.refresh_from_db()
        assert empty_account.available_balance == Money(
            Decimal("-49.06"), "USD"
        )
        assert empty_account.posted_balance == Money(Decimal("-49.06"), "USD")

        # Regression guard: the unallocated-budget balance must move in
        # lockstep with `account.available_balance`.  An earlier bug
        # filtered allocations with the wrong FK column, so the pending
        # wipe failed to reverse the budget side -- account total was
        # right, but unallocated drifted by the wiped amount.
        assert empty_account.unallocated_budget_id is not None
        unalloc = Budget.objects.get(id=empty_account.unallocated_budget_id)
        assert unalloc.balance == Money(Decimal("-49.06"), "USD")
        assert empty_account.available_balance == sum(
            (
                b.balance
                for b in Budget.objects.filter(bank_account=empty_account)
            ),
            Money(0, "USD"),
        )

    ####################################################################
    #
    def test_pending_to_posted_with_unrelated_description(
        self, empty_account: BankAccount
    ) -> None:
        """
        GIVEN: a pending ACH hold with an opaque holding description
        WHEN:  the bank settles the row and rewrites the description to
               a completely different one (zero substring overlap)
        THEN:  the new posted row exists, the stale pending row is gone.

        This is the case the old description-matching pipeline could not
        bridge.  Under the new design we never need to bridge it -- the
        pending wipe covers any stale row regardless of its description.
        """
        pending = _payload(
            ending_balance=Decimal("-292.22"),
            transactions=[
                _stx(
                    pending=True,
                    posted_date=datetime(2026, 5, 19, 8, 0, tzinfo=UTC),
                    raw_description=("ACH HOLD WIDGETCARD CO PAYMENT ON 03/07"),
                    amount=Decimal("-292.22"),
                ),
            ],
        )
        sync_scrape_svc.sync_scrape(empty_account, pending)

        posted = _payload(
            ending_balance=Decimal("-292.22"),
            transactions=[
                _stx(
                    pending=False,
                    posted_date=datetime(2026, 5, 18, 0, 0, tzinfo=UTC),
                    raw_description=(
                        "WIDGETCARD CO DES:PAYMENT ID:837192 "
                        "INDN:USER NAME CO ID:XXXXX46721 WEB"
                    ),
                    amount=Decimal("-292.22"),
                    transaction_type="ach",
                ),
            ],
        )
        report = sync_scrape_svc.sync_scrape(empty_account, posted)
        assert report.deleted_pending == 1
        assert report.inserted_posted == 1

        rows = list(Transaction.objects.filter(bank_account=empty_account))
        assert len(rows) == 1
        assert rows[0].pending is False
        assert "WIDGETCARD CO DES:PAYMENT" in rows[0].raw_description

    ####################################################################
    #
    def test_same_date_posted_preserves_scrape_top_to_bottom_order(
        self, empty_account: BankAccount
    ) -> None:
        """
        GIVEN: five posted rows that all share the same transaction_date
        WHEN:  sync_scrape inserts them in the scraper's newest-first
               order
        THEN:  the UI ordering `(-transaction_date, -created_at)`
               matches the scrape's top-to-bottom order, because the
               service iterates the scrape in reverse and lets
               `created_at` be the tiebreaker.
        """
        same_day = datetime(2026, 5, 18, 0, 0, tzinfo=UTC)
        # Scrape order, newest-first (i.e. how the bank shows them).
        descs = ["TX-A", "TX-B", "TX-C", "TX-D", "TX-E"]
        payload = _payload(
            ending_balance=Decimal("-50.00"),
            transactions=[
                _stx(
                    pending=False,
                    posted_date=same_day,
                    raw_description=desc,
                    amount=Decimal("-10.00"),
                )
                for desc in descs
            ],
        )
        sync_scrape_svc.sync_scrape(empty_account, payload)

        ordered = list(
            Transaction.objects.filter(bank_account=empty_account).order_by(
                "-transaction_date", "-created_at"
            )
        )
        assert [r.raw_description for r in ordered] == descs

    ####################################################################
    #
    def test_inserting_older_posted_recomputes_snapshots(
        self, empty_account: BankAccount
    ) -> None:
        """
        GIVEN: an existing posted row dated 5/18 with snapshot A
        WHEN:  a new sync inserts a posted row dated 5/15 (older)
        THEN:  the existing row's snapshots are updated to reflect the
               new chain (the 5/15 row's amount now contributes), and
               the 5/15 row's snapshots are correct for its position.
        """
        first = _payload(
            ending_balance=Decimal("-25.00"),
            transactions=[
                _stx(
                    pending=False,
                    posted_date=datetime(2026, 5, 18, 0, 0, tzinfo=UTC),
                    raw_description="NEWER TX",
                    amount=Decimal("-25.00"),
                ),
            ],
        )
        sync_scrape_svc.sync_scrape(empty_account, first)

        second = _payload(
            ending_balance=Decimal("-75.00"),
            transactions=[
                _stx(
                    pending=False,
                    posted_date=datetime(2026, 5, 18, 0, 0, tzinfo=UTC),
                    raw_description="NEWER TX",
                    amount=Decimal("-25.00"),
                ),
                _stx(
                    pending=False,
                    posted_date=datetime(2026, 5, 15, 0, 0, tzinfo=UTC),
                    raw_description="OLDER TX",
                    amount=Decimal("-50.00"),
                ),
            ],
        )
        report = sync_scrape_svc.sync_scrape(empty_account, second)
        assert report.skipped_posted == 1  # NEWER already in DB
        assert report.inserted_posted == 1  # OLDER is new

        newer = Transaction.objects.get(
            bank_account=empty_account, raw_description="NEWER TX"
        )
        older = Transaction.objects.get(
            bank_account=empty_account, raw_description="OLDER TX"
        )
        # Display order: newer on top with available=-75 (current total),
        # older below with available=-50 (pre-newer chain position).
        assert newer.bank_account_available_balance == Money(-75, "USD")
        assert newer.bank_account_posted_balance == Money(-75, "USD")
        assert older.bank_account_available_balance == Money(-50, "USD")
        assert older.bank_account_posted_balance == Money(-50, "USD")

    ####################################################################
    #
    def test_pending_wipe_preserves_account_equals_sum_of_budgets(
        self, empty_account: BankAccount
    ) -> None:
        """
        GIVEN: an account with several pending rows and several posted rows
        WHEN:  a follow-up sync wipes all pending and inserts a new pending
        THEN:  the invariant `account.available_balance ==
               sum(budget.balance)` still holds.

        This is the regression guard for the bug where the pending
        wipe used the wrong FK column to find allocations to delete,
        leaving the unallocated budget's balance unreversed while the
        account-level balance was correct.  After the bug, the
        invariant broke even though account-level totals looked fine.
        """
        seed = _payload(
            ending_balance=Decimal("-345.00"),
            transactions=[
                _stx(
                    pending=True,
                    posted_date=datetime(2026, 5, 19, 8, 0, tzinfo=UTC),
                    raw_description="PENDING ONE",
                    amount=Decimal("-100.00"),
                ),
                _stx(
                    pending=True,
                    posted_date=datetime(2026, 5, 19, 8, 0, tzinfo=UTC),
                    raw_description="PENDING TWO",
                    amount=Decimal("-200.00"),
                ),
                _stx(
                    pending=False,
                    posted_date=datetime(2026, 5, 17, 0, 0, tzinfo=UTC),
                    raw_description="POSTED ONE",
                    amount=Decimal("-45.00"),
                ),
            ],
        )
        sync_scrape_svc.sync_scrape(empty_account, seed)

        # Second sync: wipe both pending, re-add nothing pending.
        after = _payload(
            ending_balance=Decimal("-45.00"),
            transactions=[
                _stx(
                    pending=False,
                    posted_date=datetime(2026, 5, 17, 0, 0, tzinfo=UTC),
                    raw_description="POSTED ONE",
                    amount=Decimal("-45.00"),
                ),
            ],
        )
        sync_scrape_svc.sync_scrape(empty_account, after)

        empty_account.refresh_from_db()
        assert empty_account.available_balance == Money(-45, "USD")
        budgets_total = sum(
            (
                b.balance
                for b in Budget.objects.filter(bank_account=empty_account)
            ),
            Money(0, "USD"),
        )
        assert budgets_total == empty_account.available_balance, (
            f"invariant broken: account.available_balance="
            f"{empty_account.available_balance}, "
            f"sum(budget.balance)={budgets_total}"
        )

    ####################################################################
    #
    def test_balance_mismatch_reported(
        self, empty_account: BankAccount
    ) -> None:
        """
        GIVEN: a scrape whose stated `ending_balance` does not match the
               sum of its transactions
        WHEN:  sync_scrape runs
        THEN:  the report's `balance_mismatch` field is non-None and
               equals the signed difference (computed - declared); the
               sync still commits its mutations.
        """
        payload = _payload(
            ending_balance=Decimal("-1000.00"),  # claim
            transactions=[
                _stx(
                    pending=False,
                    posted_date=datetime(2026, 5, 18, 0, 0, tzinfo=UTC),
                    raw_description="TX",
                    amount=Decimal("-25.00"),
                ),
            ],
        )
        report = sync_scrape_svc.sync_scrape(empty_account, payload)
        assert report.balance_mismatch == Decimal("975.00")
        assert report.inserted_posted == 1
        empty_account.refresh_from_db()
        assert empty_account.available_balance == Money(-25, "USD")

    ####################################################################
    #
    def test_posting_order_chain_self_inconsistency_reported(
        self, empty_account: BankAccount
    ) -> None:
        """
        GIVEN: a scrape whose per-row `running_balance` values do not
               form a consistent posting-order chain
        WHEN:  sync_scrape runs
        THEN:  `posting_order_mismatches` reports a warning describing
               the offending pair; the sync still commits.
        """
        payload = _payload(
            ending_balance=Decimal("-75.00"),
            transactions=[
                # Newer-on-top
                _stx(
                    pending=False,
                    posted_date=datetime(2026, 5, 18, 0, 0, tzinfo=UTC),
                    raw_description="NEWER TX",
                    amount=Decimal("-25.00"),
                    running_balance=Decimal("-75.00"),
                ),
                _stx(
                    pending=False,
                    posted_date=datetime(2026, 5, 17, 0, 0, tzinfo=UTC),
                    raw_description="OLDER TX",
                    # Inconsistent: -75 (newer) should be older.rb + -25.
                    # If older.rb is -10 then expected newer.rb = -35,
                    # not -75 -- mismatch.
                    amount=Decimal("-50.00"),
                    running_balance=Decimal("-10.00"),
                ),
            ],
        )
        report = sync_scrape_svc.sync_scrape(empty_account, payload)
        assert report.posting_order_mismatches
        assert "NEWER TX" in report.posting_order_mismatches[0]


########################################################################
########################################################################
#
class TestSyncScrapeValidation:
    """Tests for the input-validation guard rails on sync_scrape."""

    ####################################################################
    #
    def test_missing_unallocated_budget_raises(
        self,
        bank_account_factory: Callable[..., BankAccount],
        user_factory: Callable[..., User],
    ) -> None:
        """
        GIVEN: a bank account whose unallocated_budget is None
        WHEN:  sync_scrape is called
        THEN:  ValueError is raised before any mutation happens
        """
        user = user_factory()
        account = bank_account_factory(owners=[user], currency="USD")
        BankAccount.objects.filter(pkid=account.pkid).update(
            unallocated_budget=None
        )
        account.refresh_from_db()

        with pytest.raises(ValueError, match="unallocated_budget"):
            sync_scrape_svc.sync_scrape(
                account,
                _payload(
                    ending_balance=Decimal("0"),
                    transactions=[],
                ),
            )

    ####################################################################
    #
    def test_currency_mismatch_raises(
        self,
        bank_account_factory: Callable[..., BankAccount],
        user_factory: Callable[..., User],
    ) -> None:
        """
        GIVEN: a USD account and a scrape that lists a EUR transaction
        WHEN:  sync_scrape is called
        THEN:  ValueError is raised before any mutation happens
        """
        user = user_factory()
        account = bank_account_factory(owners=[user], currency="USD")
        payload = sync_scrape_svc.ScrapeSyncPayload(
            scraped_at=datetime(2026, 5, 19, 12, 0, tzinfo=UTC),
            ending_balance=Money(0, "USD"),
            transactions=[
                sync_scrape_svc.ScrapedTransaction(
                    is_pending=False,
                    posted_date=datetime(2026, 5, 18, 0, 0, tzinfo=UTC),
                    raw_description="EUR TX",
                    amount=Money(Decimal("-10.00"), "EUR"),
                ),
            ],
        )
        with pytest.raises(ValueError, match="currency"):
            sync_scrape_svc.sync_scrape(account, payload)


########################################################################
########################################################################
#
# Anonymised description pairs modelled on real BofA scrape vs CSV/OFX
# import contrasts.  The bank's web UI truncates long ACH descriptions
# at a roughly-fixed pixel width; the trailing literal '...' is the
# only marker.  Lengths observed in one set of real scrapes were 63,
# 64, and 66 characters before the '...'.  The merchant and customer
# names below are made up; real entity / account IDs are never
# encoded into test fixtures.
#
_FULL_ACH_TRANSFER = (
    "ACMECORP BRK SVC DES:TRANSFER ID:XXXXX1234 ZN8K3 "
    "INDN:USER NAME CO ID:XXXXX98765 WEB"
)
_TRUNC_ACH_TRANSFER = (
    "ACMECORP BRK SVC DES:TRANSFER ID:XXXXX1234 ZN8K3 INDN:USER NAME CO..."
)
_FULL_AGENCY_FEE = (
    "WIDGETPERMIT AGENCY DES:PURCHASE ID:YYYYYYYYYY56789 "
    "INDN:OTHER NAME CO ID:YYYYY43210 WEB"
)
_TRUNC_AGENCY_FEE = (
    "WIDGETPERMIT AGENCY DES:PURCHASE ID:YYYYYYYYYY56789 INDN:OTHER NAME..."
)


########################################################################
########################################################################
#
class TestMatchesTruncated:
    """Unit tests for `sync_scrape._matches_truncated`."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "scraped,candidates,expected,reason",
        [
            # Exact match always wins.
            (
                _FULL_ACH_TRANSFER,
                [_FULL_ACH_TRANSFER],
                True,
                "exact match against full",
            ),
            (
                _TRUNC_ACH_TRANSFER,
                [_TRUNC_ACH_TRANSFER],
                True,
                "exact match against truncated",
            ),
            # The canonical bug scenario: scrape comes in truncated,
            # backup has the full row.
            (
                _TRUNC_ACH_TRANSFER,
                [_FULL_ACH_TRANSFER],
                True,
                "scraped truncated, candidate full -- ACH TRANSFER",
            ),
            (
                _TRUNC_AGENCY_FEE,
                [_FULL_AGENCY_FEE],
                True,
                "scraped truncated, candidate full -- agency fee",
            ),
            # Reverse direction: a stored row is the truncated one, a
            # later scrape produces the full description.  Symmetric
            # support keeps the dedup right when BofA's truncation
            # policy changes (or when manual CSV imports happen after
            # an earlier scrape).
            (
                _FULL_ACH_TRANSFER,
                [_TRUNC_ACH_TRANSFER],
                True,
                "scraped full, candidate truncated",
            ),
            # No match cases.
            (
                _FULL_ACH_TRANSFER,
                [_FULL_AGENCY_FEE],
                False,
                "different transactions, no prefix relationship",
            ),
            (
                _TRUNC_ACH_TRANSFER,
                [_FULL_AGENCY_FEE],
                False,
                "scraped truncated but no candidate shares the stem",
            ),
            (
                "ANY DESCRIPTION",
                [],
                False,
                "no candidates",
            ),
            # Walks the candidates list and returns True on the first hit.
            (
                _TRUNC_ACH_TRANSFER,
                [_FULL_AGENCY_FEE, _FULL_ACH_TRANSFER],
                True,
                "matches second candidate",
            ),
            # Two distinct truncated rows in the same (date, amount)
            # bucket: as long as one is a prefix of the other (after
            # stripping `...`) we treat as match.  This is rare but
            # supports the case where a backup contains a slightly
            # older truncation that's a prefix of a newer truncation.
            (
                "PREFIX SAME EXTRA...",
                ["PREFIX SAME..."],
                True,
                "scraped longer truncated, candidate shorter truncated",
            ),
        ],
    )
    def test_match_table(
        self,
        scraped: str,
        candidates: list[str],
        expected: bool,
        reason: str,
    ) -> None:
        """Parametrised cases for the truncation-rescue rule."""
        actual = sync_scrape_svc._matches_truncated(scraped, candidates)
        assert actual is expected, reason


########################################################################
########################################################################
#
class TestSyncScrapeTruncatedDedup:
    """End-to-end: truncated scraped descriptions dedup against full
    stored descriptions inside `sync_scrape`.
    """

    ####################################################################
    #
    def test_scraped_truncated_matches_existing_full(
        self, empty_account: BankAccount
    ) -> None:
        """
        GIVEN: two posted rows already in the DB with FULL descriptions
               (the kind a CSV / OFX import produces)
        WHEN:  a sync_scrape runs with the same two rows but with
               BofA-style truncated descriptions ending in `...`
        THEN:  no new rows are inserted (both skipped via truncation
               rescue), account and budget balances are unchanged.

        This is the canonical real-world bug: backup data carries the
        full descriptions, but the web-UI scraper sees them truncated.
        Strict (date, amount, raw_description) dedup misses the match;
        the prefix rescue catches it.
        """
        # Seed the account with the two FULL-description posted rows.
        seed = _payload(
            ending_balance=Decimal("-1090.00"),
            transactions=[
                _stx(
                    pending=False,
                    posted_date=datetime(2026, 1, 27, 0, 0, tzinfo=UTC),
                    raw_description=_FULL_ACH_TRANSFER,
                    amount=Decimal("-800.00"),
                    transaction_type="ach",
                ),
                _stx(
                    pending=False,
                    posted_date=datetime(2026, 3, 26, 0, 0, tzinfo=UTC),
                    raw_description=_FULL_AGENCY_FEE,
                    amount=Decimal("-290.00"),
                    transaction_type="ach",
                ),
            ],
        )
        seed_report = sync_scrape_svc.sync_scrape(empty_account, seed)
        assert seed_report.inserted_posted == 2
        assert seed_report.balance_mismatch is None

        # Second sync: SAME two rows, but with truncated descriptions
        # as BofA's web UI renders them.  Should dedup, not duplicate.
        scrape = _payload(
            ending_balance=Decimal("-1090.00"),
            transactions=[
                _stx(
                    pending=False,
                    posted_date=datetime(2026, 1, 27, 0, 0, tzinfo=UTC),
                    raw_description=_TRUNC_ACH_TRANSFER,
                    amount=Decimal("-800.00"),
                    transaction_type="ach",
                ),
                _stx(
                    pending=False,
                    posted_date=datetime(2026, 3, 26, 0, 0, tzinfo=UTC),
                    raw_description=_TRUNC_AGENCY_FEE,
                    amount=Decimal("-290.00"),
                    transaction_type="ach",
                ),
            ],
        )
        report = sync_scrape_svc.sync_scrape(empty_account, scrape)

        assert report.inserted_posted == 0
        assert report.skipped_posted == 2
        assert report.balance_mismatch is None

        empty_account.refresh_from_db()
        assert empty_account.available_balance == Money(-1090, "USD")
        assert (
            Transaction.objects.filter(bank_account=empty_account).count() == 2
        )

    ####################################################################
    #
    def test_scraped_full_matches_existing_truncated(
        self, empty_account: BankAccount
    ) -> None:
        """
        GIVEN: a posted row already in the DB with a TRUNCATED `...`
               description (from a prior scrape)
        WHEN:  a sync_scrape runs with the same row but expanded to
               its full description (e.g., a subsequent CSV or OFX
               import or BofA's UI un-truncating it)
        THEN:  no new row is inserted -- the truncation rescue is
               symmetric.
        """
        seed = _payload(
            ending_balance=Decimal("-800.00"),
            transactions=[
                _stx(
                    pending=False,
                    posted_date=datetime(2026, 1, 27, 0, 0, tzinfo=UTC),
                    raw_description=_TRUNC_ACH_TRANSFER,
                    amount=Decimal("-800.00"),
                    transaction_type="ach",
                ),
            ],
        )
        sync_scrape_svc.sync_scrape(empty_account, seed)

        scrape = _payload(
            ending_balance=Decimal("-800.00"),
            transactions=[
                _stx(
                    pending=False,
                    posted_date=datetime(2026, 1, 27, 0, 0, tzinfo=UTC),
                    raw_description=_FULL_ACH_TRANSFER,
                    amount=Decimal("-800.00"),
                    transaction_type="ach",
                ),
            ],
        )
        report = sync_scrape_svc.sync_scrape(empty_account, scrape)

        assert report.inserted_posted == 0
        assert report.skipped_posted == 1
        assert (
            Transaction.objects.filter(bank_account=empty_account).count() == 1
        )

    ####################################################################
    #
    def test_truncation_rescue_does_not_collapse_distinct_amounts(
        self, empty_account: BankAccount
    ) -> None:
        """
        GIVEN: an existing posted row at $-800 with the FULL ACH TRANSFER
               description, and a scrape that brings in a DIFFERENT
               ACH transfer at $-790 with a TRUNCATED description
        WHEN:  sync_scrape runs
        THEN:  the truncation rescue does NOT fire (amounts differ),
               so the new $-790 row is inserted as a fresh
               transaction.  The (date, amount) bucket is the safety
               rail that keeps the rescue from collapsing distinct
               charges to the same merchant.
        """
        seed = _payload(
            ending_balance=Decimal("-800.00"),
            transactions=[
                _stx(
                    pending=False,
                    posted_date=datetime(2026, 1, 27, 0, 0, tzinfo=UTC),
                    raw_description=_FULL_ACH_TRANSFER,
                    amount=Decimal("-800.00"),
                    transaction_type="ach",
                ),
            ],
        )
        sync_scrape_svc.sync_scrape(empty_account, seed)

        scrape = _payload(
            ending_balance=Decimal("-1590.00"),
            transactions=[
                _stx(
                    pending=False,
                    posted_date=datetime(2026, 1, 27, 0, 0, tzinfo=UTC),
                    raw_description=_FULL_ACH_TRANSFER,
                    amount=Decimal("-800.00"),
                    transaction_type="ach",
                ),
                _stx(
                    pending=False,
                    posted_date=datetime(2026, 1, 28, 0, 0, tzinfo=UTC),
                    raw_description=_TRUNC_ACH_TRANSFER,
                    amount=Decimal("-790.00"),
                    transaction_type="ach",
                ),
            ],
        )
        report = sync_scrape_svc.sync_scrape(empty_account, scrape)

        assert report.inserted_posted == 1
        assert report.skipped_posted == 1
        assert (
            Transaction.objects.filter(bank_account=empty_account).count() == 2
        )

    ####################################################################
    #
    def test_in_payload_truncated_does_not_re_match_just_inserted(
        self, empty_account: BankAccount
    ) -> None:
        """
        GIVEN: a single sync payload that contains both a FULL and a
               TRUNCATED version of the same (date, amount, merchant)
               -- e.g., the scraper somehow surfaced both
        WHEN:  sync_scrape processes them in scrape order
        THEN:  only the first wins; the second is treated as a
               duplicate via in-payload reindex (no two-row insert).
        """
        scrape = _payload(
            ending_balance=Decimal("-800.00"),
            transactions=[
                _stx(
                    pending=False,
                    posted_date=datetime(2026, 1, 27, 0, 0, tzinfo=UTC),
                    raw_description=_FULL_ACH_TRANSFER,
                    amount=Decimal("-800.00"),
                    transaction_type="ach",
                ),
                _stx(
                    pending=False,
                    posted_date=datetime(2026, 1, 27, 0, 0, tzinfo=UTC),
                    raw_description=_TRUNC_ACH_TRANSFER,
                    amount=Decimal("-800.00"),
                    transaction_type="ach",
                ),
            ],
        )
        report = sync_scrape_svc.sync_scrape(empty_account, scrape)
        assert report.inserted_posted == 1
        assert report.skipped_posted == 1
        assert (
            Transaction.objects.filter(bank_account=empty_account).count() == 1
        )
