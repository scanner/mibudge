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
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, call

# 3rd party imports
#
import pytest
import pytest_check as check
from djmoney.money import Money
from pytest_mock import MockerFixture

# Project imports
#
from moneypools.models import BankAccount, Budget, Transaction
from moneypools.notification_kinds import (
    BALANCE_MISMATCH,
    IMPORT_COMPLETE,
    IMPORT_ERROR,
    TRANSACTION_POSTED,
)
from moneypools.service import sync_scrape as sync_scrape_svc
from notifications.models import (
    DeliveryMode,
    Notification,
    NotificationPreference,
)
from users.models import User

from .conftest import MerchantPlace

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
    bank_account_factory: Callable[..., BankAccount], user: User
) -> BankAccount:
    """A BankAccount with zero balance, owned by the default `user`."""
    return bank_account_factory(
        owners=[user],
        currency="USD",
        available_balance=Money(0, "USD"),
        posted_balance=Money(0, "USD"),
    )


########################################################################
########################################################################
#
@pytest.mark.usefixtures("mock_send_notification_now")
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

        check.equal(
            (
                report.deleted_pending,
                report.inserted_posted,
                report.skipped_posted,
                report.inserted_pending,
            ),
            (0, 2, 0, 1),
            "report counts (deleted, posted, skipped, pending)",
        )
        check.is_none(report.balance_mismatch, "balances agree")
        check.equal(
            report.last_posted_through,
            date(2026, 5, 18),
            "last_posted_through is the latest posted date",
        )
        check.equal(len(report.new_transaction_ids), 3, "three new ids")

        empty_account.refresh_from_db()
        check.equal(
            empty_account.available_balance, Money(-85, "USD"), "available"
        )
        # posted_balance excludes pending
        check.equal(empty_account.posted_balance, Money(-75, "USD"), "posted")

        # Display order `(-transaction_date, -created_at)` must reproduce
        # the scrape's top-to-bottom order, because the service inserts
        # same-date rows in reverse-scrape order so the topmost-in-scrape
        # gets the highest `created_at`.
        rows = list(
            Transaction.objects.filter(bank_account=empty_account).order_by(
                "-transaction_date", "-created_at"
            )
        )
        check.equal(
            [r.raw_description for r in rows],
            ["PURCHASE PENDING THING", "POSTED THING B", "POSTED THING A"],
            "display order is scrape order",
        )
        # Snapshots are the running balance after this row, walked
        # newest-first from the current account totals.  Pending tx
        # itself shows the current posted_balance (-75) because it has
        # not yet posted.
        check.equal(
            [
                (
                    r.bank_account_available_balance.amount,
                    r.bank_account_posted_balance.amount,
                )
                for r in rows
            ],
            [(-85, -75), (-75, -75), (-50, -50)],
            "(available, posted) snapshots",
        )

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

        check.equal(
            (first.inserted_posted, first.inserted_pending),
            (1, 1),
            "first run inserts both",
        )
        check.equal(
            (
                second.inserted_posted,
                second.skipped_posted,
                second.deleted_pending,
                second.inserted_pending,
            ),
            (0, 1, 1, 1),
            "second run skips posted, replaces pending",
        )

        empty_account.refresh_from_db()
        check.equal(
            empty_account.available_balance, Money(-35, "USD"), "available"
        )
        check.equal(
            Transaction.objects.filter(bank_account=empty_account).count(),
            2,
            "no duplicates",
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
        check.equal(
            (report.deleted_pending, report.inserted_pending),
            (1, 1),
            "pending replaced",
        )
        check.equal(
            list(
                Transaction.objects.filter(
                    bank_account=empty_account, pending=True
                ).values_list("raw_description", flat=True)
            ),
            ["PURCHASE Acmecorp Co/bill ZZ ON 03/07"],
            "one pending row with the new description",
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
        check.equal(
            (
                report.deleted_pending,
                report.inserted_posted,
                report.inserted_pending,
            ),
            (1, 1, 0),
            "pending wiped, posted inserted",
        )
        check.is_none(report.balance_mismatch, "balances agree")

        final = Money(Decimal("-49.06"), "USD")
        check.equal(
            [
                (r.pending, r.amount)
                for r in Transaction.objects.filter(bank_account=empty_account)
            ],
            [(False, final)],
            "one posted row at the final amount",
        )

        empty_account.refresh_from_db()
        check.equal(empty_account.available_balance, final, "available")
        check.equal(empty_account.posted_balance, final, "posted")

        # Regression guard: the unallocated-budget balance must move in
        # lockstep with `account.available_balance`.  An earlier bug
        # filtered allocations with the wrong FK column, so the pending
        # wipe failed to reverse the budget side -- account total was
        # right, but unallocated drifted by the wiped amount.
        assert empty_account.unallocated_budget_id is not None
        unalloc = Budget.objects.get(id=empty_account.unallocated_budget_id)
        check.equal(unalloc.balance, final, "Unallocated follows")
        check.equal(
            empty_account.available_balance,
            sum(
                (
                    b.balance
                    for b in Budget.objects.filter(bank_account=empty_account)
                ),
                Money(0, "USD"),
            ),
            "account equals sum of budgets",
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
        check.equal(
            (report.deleted_pending, report.inserted_posted),
            (1, 1),
            "pending wiped, posted inserted",
        )

        rows = list(Transaction.objects.filter(bank_account=empty_account))
        assert len(rows) == 1
        check.is_false(rows[0].pending, "the row is posted")
        check.is_in(
            "WIDGETCARD CO DES:PAYMENT",
            rows[0].raw_description,
            "with the settled description",
        )

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
        # NEWER is already in the DB; OLDER is new.
        check.equal(
            (report.skipped_posted, report.inserted_posted),
            (1, 1),
            "newer skipped, older inserted",
        )

        newer = Transaction.objects.get(
            bank_account=empty_account, raw_description="NEWER TX"
        )
        older = Transaction.objects.get(
            bank_account=empty_account, raw_description="OLDER TX"
        )
        # Display order: newer on top with available=-75 (current total),
        # older below with available=-50 (pre-newer chain position).
        check.equal(
            [
                (
                    r.bank_account_available_balance.amount,
                    r.bank_account_posted_balance.amount,
                )
                for r in (newer, older)
            ],
            [(-75, -75), (-50, -50)],
            "(available, posted) snapshots of newer, older",
        )

    ####################################################################
    #
    def test_dedup_window_floor_uses_transaction_date_not_posted_date(
        self, empty_account: BankAccount, merchant_place: MerchantPlace
    ) -> None:
        """
        GIVEN: an existing posted row with posted_date 01/26 but
               transaction_date 01/24 (parsed from the MM/DD in the
               description), and it is the OLDEST row in the next scrape
        WHEN:  the next scrape lists the identical row
        THEN:  the dedup query finds the existing row and the scrape is
               skipped instead of inserting a duplicate.

        Regression: the dedup window used to derive its bounds from
        scrape posted_dates while the filter ran against
        transaction_date.  When the oldest scraped row had a
        transaction_date earlier than (oldest_posted_date - pad), its
        existing duplicate fell below the window floor and was missed,
        producing one new duplicate per scrape.
        """
        # Use a description with embedded "01/24" so the parsed
        # transaction_date lands two days before posted_date 01/26.
        # This is the exact shape that broke joint-checking imports.
        seed = _payload(
            ending_balance=Decimal("-234.28"),
            transactions=[
                _stx(
                    pending=False,
                    posted_date=datetime(2026, 1, 26, 8, 0, tzinfo=UTC),
                    raw_description=(
                        "COSTCO WHSE #481 01/24 MOBILE PURCHASE "
                        f"{merchant_place.city.upper()} {merchant_place.region}"
                    ),
                    amount=Decimal("-234.28"),
                ),
            ],
        )
        sync_scrape_svc.sync_scrape(empty_account, seed)

        # Sanity: the seed row is present with transaction_date < posted_date.
        seeded = Transaction.objects.get(bank_account=empty_account)
        assert seeded.transaction_date.date() == date(2026, 1, 24)
        assert seeded.posted_date.date() == date(2026, 1, 26)

        # Resync with the same row as the OLDEST in the scrape (the only
        # row whose posted_date defines `min`).  The pre-fix code would
        # set min_date = 2026-01-26 - 1 day = 2026-01-25, excluding the
        # existing transaction_date 2026-01-24 from the dedup map.
        report = sync_scrape_svc.sync_scrape(empty_account, seed)
        check.equal(
            (report.inserted_posted, report.skipped_posted),
            (0, 1),
            "skipped as a duplicate",
        )
        check.equal(
            Transaction.objects.filter(bank_account=empty_account).count(),
            1,
            "no duplicate row",
        )

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
        budgets_total = sum(
            (
                b.balance
                for b in Budget.objects.filter(bank_account=empty_account)
            ),
            Money(0, "USD"),
        )
        check.equal(
            empty_account.available_balance, Money(-45, "USD"), "available"
        )
        check.equal(
            budgets_total,
            empty_account.available_balance,
            "account equals sum of budgets",
        )

    ####################################################################
    #
    def test_balance_mismatch_reported(
        self,
        empty_account: BankAccount,
        user: User,
        mock_send_notification_now: MagicMock,
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
        check.equal(report.balance_mismatch, Decimal("975.00"), "the diff")
        check.equal(report.inserted_posted, 1, "the row still commits")
        empty_account.refresh_from_db()
        check.equal(
            empty_account.available_balance, Money(-25, "USD"), "available"
        )

        n = Notification.objects.get(user=user, kind=BALANCE_MISMATCH)
        check.is_true(
            {
                "account_name",
                "account_id",
                "computed_balance",
                "reported_balance",
                "diff",
            }
            <= n.context.keys(),
            "notification context has every key",
        )
        check.equal(
            n.context["account_id"], str(empty_account.id), "names the account"
        )
        check.is_in(
            call(str(n.id)),
            mock_send_notification_now.delay.call_args_list,
            "sent now",
        )

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
        self, empty_account: BankAccount
    ) -> None:
        """
        GIVEN: a bank account whose unallocated_budget is None
        WHEN:  sync_scrape is called
        THEN:  ValueError is raised before any mutation happens
        """
        BankAccount.objects.filter(pkid=empty_account.pkid).update(
            unallocated_budget=None
        )
        empty_account.refresh_from_db()

        with pytest.raises(ValueError, match="unallocated_budget"):
            sync_scrape_svc.sync_scrape(
                empty_account,
                _payload(
                    ending_balance=Decimal("0"),
                    transactions=[],
                ),
            )

    ####################################################################
    #
    def test_currency_mismatch_raises(self, empty_account: BankAccount) -> None:
        """
        GIVEN: a USD account and a scrape that lists a EUR transaction
        WHEN:  sync_scrape is called
        THEN:  ValueError is raised before any mutation happens
        """
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
            sync_scrape_svc.sync_scrape(empty_account, payload)


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
def _ach_scrape(
    rows: list[tuple[str, str, int]],
) -> sync_scrape_svc.ScrapeSyncPayload:
    """Build a scrape of posted January 2026 ACH rows.

    Args:
        rows: `(raw_description, amount, day of month)` per row, in
            scrape order.  The ending balance is their sum.
    """
    return _payload(
        ending_balance=sum(
            (Decimal(amount) for _, amount, _ in rows), Decimal(0)
        ),
        transactions=[
            _stx(
                pending=False,
                posted_date=datetime(2026, 1, day, tzinfo=UTC),
                raw_description=desc,
                amount=Decimal(amount),
                transaction_type="ach",
            )
            for desc, amount, day in rows
        ],
    )


########################################################################
########################################################################
#
class TestMatchesTruncated:
    """Unit tests for `sync_scrape._matches_truncated`."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "scraped,candidates,expected_match",
        [
            # Exact match always wins.
            pytest.param(
                _FULL_ACH_TRANSFER,
                [_FULL_ACH_TRANSFER],
                _FULL_ACH_TRANSFER,
                id="exact",
            ),
            # The canonical bug scenario: scrape comes in truncated,
            # backup has the full row.
            pytest.param(
                _TRUNC_ACH_TRANSFER,
                [_FULL_ACH_TRANSFER],
                _FULL_ACH_TRANSFER,
                id="scraped_truncated_candidate_full",
            ),
            # Reverse direction: a stored row is the truncated one, a
            # later scrape produces the full description.  Symmetric
            # support keeps the dedup right when BofA's truncation
            # policy changes (or when manual CSV imports happen after
            # an earlier scrape).
            pytest.param(
                _FULL_ACH_TRANSFER,
                [_TRUNC_ACH_TRANSFER],
                _TRUNC_ACH_TRANSFER,
                id="scraped_full_candidate_truncated",
            ),
            # Two distinct truncated rows in the same (date, amount)
            # bucket: as long as one is a prefix of the other (after
            # stripping `...`) we treat as match.  This is rare but
            # supports the case where a backup contains a slightly
            # older truncation that's a prefix of a newer truncation.
            pytest.param(
                "PREFIX SAME EXTRA...",
                ["PREFIX SAME..."],
                "PREFIX SAME...",
                id="both_truncated_candidate_shorter",
            ),
            # Walks the candidates list and returns the first hit.
            pytest.param(
                _TRUNC_ACH_TRANSFER,
                [_FULL_AGENCY_FEE, _FULL_ACH_TRANSFER],
                _FULL_ACH_TRANSFER,
                id="matches_second_candidate",
            ),
            pytest.param(
                _FULL_ACH_TRANSFER,
                [_FULL_AGENCY_FEE],
                None,
                id="no_prefix_relationship",
            ),
            pytest.param(
                _TRUNC_ACH_TRANSFER,
                [_FULL_AGENCY_FEE],
                None,
                id="scraped_truncated_no_candidate_shares_stem",
            ),
            pytest.param("ANY DESCRIPTION", [], None, id="no_candidates"),
        ],
    )
    def test_match_table(
        self,
        scraped: str,
        candidates: list[str],
        expected_match: str | None,
    ) -> None:
        """
        GIVEN: a scraped description and the stored descriptions in the
               same (date, amount) bucket
        WHEN:  _matches_truncated is applied
        THEN:  it returns the first candidate that equals the scraped
               description or is its truncated/full sibling, else None
        """
        # Candidates carry (raw_description, id, has_details) so the
        # details_needed report can reference the matched row; the
        # match itself is still driven purely by the description.
        candidate_rows = [
            (desc, f"id-{i}", False) for i, desc in enumerate(candidates)
        ]
        actual = sync_scrape_svc._matches_truncated(scraped, candidate_rows)
        assert (actual[0] if actual else None) == expected_match


########################################################################
########################################################################
#
@pytest.mark.usefixtures("mock_send_notification_now")
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
        seed_report = sync_scrape_svc.sync_scrape(
            empty_account,
            _ach_scrape(
                [
                    (_FULL_ACH_TRANSFER, "-800.00", 27),
                    (_FULL_AGENCY_FEE, "-290.00", 26),
                ]
            ),
        )
        assert seed_report.inserted_posted == 2
        assert seed_report.balance_mismatch is None

        # Second sync: SAME two rows, but with truncated descriptions
        # as BofA's web UI renders them.  Should dedup, not duplicate.
        report = sync_scrape_svc.sync_scrape(
            empty_account,
            _ach_scrape(
                [
                    (_TRUNC_ACH_TRANSFER, "-800.00", 27),
                    (_TRUNC_AGENCY_FEE, "-290.00", 26),
                ]
            ),
        )

        check.equal(
            (report.inserted_posted, report.skipped_posted),
            (0, 2),
            "both skipped",
        )
        check.is_none(report.balance_mismatch, "balances agree")
        empty_account.refresh_from_db()
        check.equal(
            empty_account.available_balance,
            Money(-1090, "USD"),
            "balance unchanged",
        )
        check.equal(
            Transaction.objects.filter(bank_account=empty_account).count(),
            2,
            "no duplicate rows",
        )

    ####################################################################
    #
    @pytest.mark.parametrize(
        "seeded,scraped,expected_rows",
        [
            # The stored row is the truncated one (from a prior scrape);
            # the new scrape expands it (a CSV/OFX import, or BofA's UI
            # un-truncating it).  The rescue is symmetric.
            pytest.param(
                [(_TRUNC_ACH_TRANSFER, "-800.00", 27)],
                [(_FULL_ACH_TRANSFER, "-800.00", 27)],
                1,
                id="scraped_full_matches_existing_truncated",
            ),
            # A DIFFERENT transfer at -$790 with a truncated description:
            # the (date, amount) bucket keeps the rescue from collapsing
            # distinct charges to the same merchant.
            pytest.param(
                [(_FULL_ACH_TRANSFER, "-800.00", 27)],
                [
                    (_FULL_ACH_TRANSFER, "-800.00", 27),
                    (_TRUNC_ACH_TRANSFER, "-790.00", 28),
                ],
                2,
                id="distinct_amount_not_collapsed",
            ),
        ],
    )
    def test_stored_sibling_skipped(
        self,
        empty_account: BankAccount,
        seeded: list[tuple[str, str, int]],
        scraped: list[tuple[str, str, int]],
        expected_rows: int,
    ) -> None:
        """
        GIVEN: a stored posted row, and a scrape carrying its
               truncated/full sibling, or a same-merchant row with a
               different amount
        WHEN:  sync_scrape runs
        THEN:  exactly one scraped row is skipped as a duplicate, every
               other scraped row is inserted
        """
        sync_scrape_svc.sync_scrape(empty_account, _ach_scrape(seeded))

        report = sync_scrape_svc.sync_scrape(
            empty_account, _ach_scrape(scraped)
        )

        check.equal(report.skipped_posted, 1, "one duplicate skipped")
        check.equal(
            report.inserted_posted, len(scraped) - 1, "the rest inserted"
        )
        check.equal(
            Transaction.objects.filter(bank_account=empty_account).count(),
            expected_rows,
            "rows stored",
        )

    ####################################################################
    #
    def test_in_payload_sibling_not_reinserted(
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
        report = sync_scrape_svc.sync_scrape(
            empty_account,
            _ach_scrape(
                [
                    (_FULL_ACH_TRANSFER, "-800.00", 27),
                    (_TRUNC_ACH_TRANSFER, "-800.00", 27),
                ]
            ),
        )

        check.equal(
            (report.inserted_posted, report.skipped_posted),
            (1, 1),
            "first inserted, sibling skipped",
        )
        check.equal(
            Transaction.objects.filter(bank_account=empty_account).count(),
            1,
            "one row stored",
        )


########################################################################
########################################################################
#
@pytest.mark.usefixtures("mock_send_notification_now")
class TestSyncScrapeNotifications:
    """Tests that sync_scrape fires the expected notification kinds."""

    ####################################################################
    #
    @pytest.fixture
    def import_complete_opt_in(self, user: User) -> None:
        """Opt `user` in to IMPORT_COMPLETE, which is off by default."""
        NotificationPreference.objects.create(
            user=user, kind=IMPORT_COMPLETE, delivery_mode=DeliveryMode.DIGEST
        )

    ####################################################################
    #
    @pytest.fixture
    def one_posted(self) -> sync_scrape_svc.ScrapeSyncPayload:
        """A scrape carrying a single new posted -$25 transaction."""
        return _payload(
            ending_balance=Decimal("-25.00"),
            transactions=[
                _stx(
                    pending=False,
                    posted_date=datetime(2026, 5, 18, 0, 0, tzinfo=UTC),
                    raw_description="POSTED TX",
                    amount=Decimal("-25.00"),
                ),
            ],
        )

    ####################################################################
    #
    @pytest.mark.usefixtures("import_complete_opt_in")
    def test_import_complete_context_on_new_posted(
        self,
        empty_account: BankAccount,
        user: User,
        one_posted: sync_scrape_svc.ScrapeSyncPayload,
    ) -> None:
        """
        GIVEN: an owner opted in to IMPORT_COMPLETE, and a scrape that
               inserts one new posted transaction
        WHEN:  sync_scrape runs
        THEN:  an IMPORT_COMPLETE notification is created with every
               expected context key, naming the account
        """
        sync_scrape_svc.sync_scrape(empty_account, one_posted)

        n = Notification.objects.get(user=user, kind=IMPORT_COMPLETE)
        check.is_true(
            {
                "account_name",
                "account_id",
                "new_count",
                "cleared_pending_count",
                "date",
            }
            <= n.context.keys(),
            "context has every key",
        )
        check.equal(
            n.context["account_id"], str(empty_account.id), "names the account"
        )

    ####################################################################
    #
    def test_transaction_posted_context_on_new_posted(
        self,
        empty_account: BankAccount,
        user: User,
        one_posted: sync_scrape_svc.ScrapeSyncPayload,
    ) -> None:
        """
        GIVEN: a scrape that inserts one new posted transaction
        WHEN:  sync_scrape runs
        THEN:  a TRANSACTION_POSTED notification (on by default) is
               created listing that transaction, untruncated
        """
        sync_scrape_svc.sync_scrape(empty_account, one_posted)

        n = Notification.objects.get(user=user, kind=TRANSACTION_POSTED)
        check.is_true(
            {
                "account_name",
                "account_id",
                "count",
                "date",
                "transactions",
                "truncated",
                "remaining_count",
            }
            <= n.context.keys(),
            "context has every key",
        )
        check.equal(
            n.context["account_id"], str(empty_account.id), "names the account"
        )
        txns = n.context["transactions"]
        check.equal(
            [t["description"] for t in txns], ["POSTED TX"], "lists the row"
        )
        check.is_true(
            {"date", "amount", "budgets"} <= txns[0].keys(),
            "row has date, amount and budgets",
        )
        check.is_false(n.context["truncated"], "not truncated")
        check.equal(n.context["remaining_count"], 0, "none remaining")

    ####################################################################
    #
    def test_transaction_posted_truncates_at_15(
        self, empty_account: BankAccount, user: User
    ) -> None:
        """
        GIVEN: a scrape that inserts 16 new posted transactions
        WHEN:  sync_scrape runs
        THEN:  the TRANSACTION_POSTED notification lists only the first 15,
               truncated=True, and remaining_count=1
        """
        payload = _payload(
            ending_balance=Decimal("-400.00"),
            transactions=[
                _stx(
                    pending=False,
                    posted_date=datetime(2026, 5, 18, 0, 0, tzinfo=UTC),
                    raw_description=f"TX {i:02d}",
                    amount=Decimal("-25.00"),
                )
                for i in range(16)
            ],
        )
        sync_scrape_svc.sync_scrape(empty_account, payload)

        n = Notification.objects.get(user=user, kind=TRANSACTION_POSTED)
        check.equal(len(n.context["transactions"]), 15, "lists 15")
        check.is_true(n.context["truncated"], "truncated")
        check.equal(n.context["remaining_count"], 1, "one remaining")

    ####################################################################
    #
    @pytest.mark.usefixtures("import_complete_opt_in")
    def test_only_pending_cleared_fires_import_complete_only(
        self, empty_account: BankAccount, user: User
    ) -> None:
        """
        GIVEN: an owner opted in to IMPORT_COMPLETE, and an account with
               one pending transaction from an earlier scrape
        WHEN:  a scrape with no transactions clears that pending row
        THEN:  IMPORT_COMPLETE fires counting the cleared row;
               TRANSACTION_POSTED does not fire
        """
        seed = _payload(
            ending_balance=Decimal("-10.00"),
            transactions=[
                _stx(
                    pending=True,
                    posted_date=datetime(2026, 5, 19, 12, 0, tzinfo=UTC),
                    raw_description="PENDING TX",
                    amount=Decimal("-10.00"),
                ),
            ],
        )
        sync_scrape_svc.sync_scrape(empty_account, seed)
        # The seed fires both kinds for the new pending tx; clear them
        # so only the second (empty) sync is checked.
        Notification.objects.filter(user=user).delete()

        sync_scrape_svc.sync_scrape(
            empty_account,
            _payload(ending_balance=Decimal("0"), transactions=[]),
        )

        n = Notification.objects.get(user=user, kind=IMPORT_COMPLETE)
        check.equal(n.context["cleared_pending_count"], 1, "counts the clear")
        check.is_false(
            Notification.objects.filter(
                user=user, kind=TRANSACTION_POSTED
            ).exists(),
            "no TRANSACTION_POSTED",
        )

    ####################################################################
    #
    @pytest.mark.usefixtures("import_complete_opt_in")
    def test_import_complete_fires_when_nothing_changed(
        self, empty_account: BankAccount, user: User
    ) -> None:
        """
        GIVEN: an owner opted in to IMPORT_COMPLETE, and a scrape that
               returns no transactions at all
        WHEN:  sync_scrape runs
        THEN:  IMPORT_COMPLETE still fires so the user knows an import
               ran, with zero counts
        """
        sync_scrape_svc.sync_scrape(
            empty_account,
            _payload(ending_balance=Decimal("0"), transactions=[]),
        )

        n = Notification.objects.get(user=user, kind=IMPORT_COMPLETE)
        check.equal(n.context["new_count"], 0, "no new rows")
        check.equal(n.context["cleared_pending_count"], 0, "none cleared")

    ####################################################################
    #
    def test_import_error_notification(
        self,
        empty_account: BankAccount,
        user: User,
        mocker: MockerFixture,
    ) -> None:
        """
        GIVEN: _sync_scrape_locked raises an unexpected exception
        WHEN:  sync_scrape runs
        THEN:  an IMPORT_ERROR notification is created with account_id
               and error context, and the exception is re-raised
        """
        mocker.patch(
            "moneypools.service.sync_scrape._sync_scrape_locked",
            side_effect=RuntimeError("scraper failed"),
        )

        with pytest.raises(RuntimeError):
            sync_scrape_svc.sync_scrape(
                empty_account,
                _payload(ending_balance=Decimal("0"), transactions=[]),
            )

        n = Notification.objects.get(user=user, kind=IMPORT_ERROR)
        check.equal(
            n.context["account_id"], str(empty_account.id), "names the account"
        )
        check.is_in("error", n.context, "carries the error")
        # Queued for the digest, not sent immediately.
        check.is_none(n.log_entry, "queued for digest")


########################################################################
########################################################################
#
@pytest.mark.usefixtures("mock_send_notification_now")
class TestSyncScrapeDetailsNeeded:
    """Tests for the details_needed report of `sync_scrape`."""

    ####################################################################
    #
    def test_new_posted_rows_listed_newest_first(
        self, empty_account: BankAccount
    ) -> None:
        """
        GIVEN: a scrape with a pending row and two new posted rows
        WHEN:  sync_scrape runs
        THEN:  details_needed lists only the posted rows, index
               ascending (the payload's newest-first order), each
               correlated to its inserted transaction
        """
        payload = _payload(
            ending_balance=Decimal("70.00"),
            transactions=[
                _stx(
                    pending=True,
                    posted_date=datetime(2026, 5, 19, 12, 0, tzinfo=UTC),
                    raw_description="PENDING COFFEE",
                    amount=Decimal("-5.00"),
                ),
                _stx(
                    pending=False,
                    posted_date=datetime(2026, 5, 18, tzinfo=UTC),
                    raw_description="POSTED NEWER",
                    amount=Decimal("-10.00"),
                ),
                _stx(
                    pending=False,
                    posted_date=datetime(2026, 5, 17, tzinfo=UTC),
                    raw_description="POSTED OLDER",
                    amount=Decimal("85.00"),
                ),
            ],
        )

        report = sync_scrape_svc.sync_scrape(empty_account, payload)

        by_desc = {
            t.raw_description: str(t.id)
            for t in Transaction.objects.filter(bank_account=empty_account)
        }
        assert [
            (row.index, row.transaction_id) for row in report.details_needed
        ] == [(1, by_desc["POSTED NEWER"]), (2, by_desc["POSTED OLDER"])]

    ####################################################################
    #
    def test_enriched_duplicates_are_not_relisted(
        self, empty_account: BankAccount
    ) -> None:
        """
        GIVEN: a prior sync whose rows were partially enriched
        WHEN:  the same scrape is synced again
        THEN:  details_needed lists only the still-unenriched
               duplicate, pointing at the EXISTING row's id
        """
        payload = _payload(
            ending_balance=Decimal("75.00"),
            transactions=[
                _stx(
                    pending=False,
                    posted_date=datetime(2026, 5, 18, tzinfo=UTC),
                    raw_description="POSTED ENRICHED",
                    amount=Decimal("-10.00"),
                ),
                _stx(
                    pending=False,
                    posted_date=datetime(2026, 5, 17, tzinfo=UTC),
                    raw_description="POSTED UNENRICHED",
                    amount=Decimal("85.00"),
                ),
            ],
        )
        sync_scrape_svc.sync_scrape(empty_account, payload)

        enriched = Transaction.objects.get(
            bank_account=empty_account, raw_description="POSTED ENRICHED"
        )
        enriched.details = {"merchant_name": "Enriched Mart"}
        enriched.save()
        unenriched = Transaction.objects.get(
            bank_account=empty_account, raw_description="POSTED UNENRICHED"
        )

        report = sync_scrape_svc.sync_scrape(empty_account, payload)

        check.equal(
            (report.inserted_posted, report.skipped_posted),
            (0, 2),
            "both skipped",
        )
        check.equal(
            [(row.index, row.transaction_id) for row in report.details_needed],
            [(1, str(unenriched.id))],
            "only the unenriched row listed",
        )

    ####################################################################
    #
    def test_truncation_rescued_duplicate_is_listed(
        self, empty_account: BankAccount
    ) -> None:
        """
        GIVEN: a stored full-description row without details and a
               scrape carrying its truncated sibling
        WHEN:  sync_scrape runs
        THEN:  the row dedups via truncation rescue and still appears
               in details_needed with the existing row's id
        """
        full, truncated = _FULL_ACH_TRANSFER, _TRUNC_ACH_TRANSFER
        first = _payload(
            ending_balance=Decimal("-10.00"),
            transactions=[
                _stx(
                    pending=False,
                    posted_date=datetime(2026, 5, 18, tzinfo=UTC),
                    raw_description=full,
                    amount=Decimal("-10.00"),
                ),
            ],
        )
        sync_scrape_svc.sync_scrape(empty_account, first)
        stored = Transaction.objects.get(
            bank_account=empty_account, raw_description=full
        )

        second = _payload(
            ending_balance=Decimal("-10.00"),
            transactions=[
                _stx(
                    pending=False,
                    posted_date=datetime(2026, 5, 18, tzinfo=UTC),
                    raw_description=truncated,
                    amount=Decimal("-10.00"),
                ),
            ],
        )
        report = sync_scrape_svc.sync_scrape(empty_account, second)

        check.equal(report.skipped_posted, 1, "deduped by the rescue")
        check.equal(
            [(row.index, row.transaction_id) for row in report.details_needed],
            [(0, str(stored.id))],
            "listed with the stored row's id",
        )
