#!/usr/bin/env python
#
"""
Tests for the budget funding engine (moneypools/service/funding.py),
the fund_budgets management command, the Celery fan-out tasks, and the
mark-imported REST endpoint.

Accounts come from `make_account` (freshness pointer and Unallocated
balance) and budgets from `make_budget` (created through the budget
service, then moved to the state a scenario starts from).
"""

# system imports
#
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, call

# 3rd party imports
#
import pytest
import pytest_check as check
import recurrence
from django.urls import reverse
from djmoney.money import Money
from freezegun import freeze_time
from pytest_mock import MockerFixture
from rest_framework.test import APIClient

# Project imports
#
from moneypools.models import (
    BankAccount,
    Budget,
    EventKind,
    FundingEventOccurrence,
    InternalTransaction,
)
from moneypools.notification_kinds import (
    FUNDING_COMPLETE,
    RECURRING_BUDGET_REFRESHED,
)
from moneypools.service import budget as budget_svc
from moneypools.service import funding as funding_svc
from moneypools.service import internal_transaction as internal_transaction_svc
from moneypools.service.funding_strategy import _fill_amount_prorated
from moneypools.tasks import (
    fund_one_account,
    recur_one_account,
    schedule_funding_runs,
)
from notifications.models import Notification
from users.models import User

pytestmark = pytest.mark.django_db

# Fires on the 1st of each month -- dtstart on the Recurrence is what
# the library uses to anchor the day-of-month; the Rule alone is ignored.
_MONTHLY = recurrence.Recurrence(
    dtstart=datetime(2026, 1, 1),
    rrules=[recurrence.Rule(recurrence.MONTHLY)],
)

# Fires on the 10th and 20th of each month -- two events per monthly cycle.
_TWICE_MONTHLY = recurrence.Recurrence(
    dtstart=datetime(2026, 2, 10),
    rrules=[recurrence.Rule(recurrence.MONTHLY, bymonthday=[10, 20])],
)

# Fires on the 1st of each month -- used as a recurrence reset anchor.
_MONTHLY_FIRST = recurrence.Recurrence(
    dtstart=datetime(2026, 2, 1),
    rrules=[recurrence.Rule(recurrence.MONTHLY)],
)

# Fires on the 15th and last day of each month -- matches the real-world
# semi-monthly funding schedule used in the joint checking account.
_TWICE_MONTHLY_15_EOM = recurrence.Recurrence(
    dtstart=datetime(2026, 1, 15),
    rrules=[recurrence.Rule(recurrence.MONTHLY, bymonthday=[15, -1])],
)

# Recurrence reset on the 1st of each month, first cycle starting May 2026.
# DTSTART=May 1 means _prev_recurrence_boundary returns None for any date
# before May 1, which is the trigger for the pre-cycle code path.
_MONTHLY_MAY_FIRST = recurrence.Recurrence(
    dtstart=datetime(2026, 5, 1),
    rrules=[recurrence.Rule(recurrence.MONTHLY)],
)

# Annual recurrence on Sep 15, starting Sep 15, 2026.  Models a yearly budget
# whose first full cycle runs Sep 15, 2025 (theoretical) to Sep 15, 2026.
# DTSTART in the future means _prev_recurrence_boundary returns None for any
# date before Sep 15, 2026, exercising the theoretical-prior-boundary path.
_YEARLY_SEP_15 = recurrence.Recurrence(
    dtstart=datetime(2026, 9, 15),
    rrules=[recurrence.Rule(recurrence.YEARLY)],
)

# The goal most engine tests fund: $50 a month toward $300.
_SNEAKERS: dict[str, Any] = {
    "budget_type": Budget.BudgetType.GOAL,
    "funding_type": Budget.FundingType.FIXED_AMOUNT,
    "target_balance": Money(300, "USD"),
    "funding_amount": Money(50, "USD"),
    "funding_schedule": _MONTHLY,
}

# A $100 monthly Recurring budget that also recurs monthly.
_BILLS: dict[str, Any] = {
    "budget_type": Budget.BudgetType.RECURRING,
    "funding_type": Budget.FundingType.TARGET_DATE,
    "target_balance": Money(100, "USD"),
    "funding_schedule": _MONTHLY,
    "recurrence_schedule": _MONTHLY,
}

# America/New_York is UTC-4 in May (EDT).
_TZ_NY = "America/New_York"


########################################################################
########################################################################
#
class TestFundingEngineSingleEvent:
    """End-to-end: single funding event for FIXED_AMOUNT and TARGET_DATE."""

    ####################################################################
    #
    def test_fixed_amount_transfers_from_unallocated_to_budget(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
        system_user: User,
    ) -> None:
        """
        GIVEN: a GOAL budget with FIXED_AMOUNT $50/month, unallocated=$200,
               last_posted_through covers today
        WHEN:  fund_account is called
        THEN:  $50 is transferred; last_funded_on advances; 1 transfer reported
        """
        today = date(2026, 3, 1)
        account = make_account(posted_through=today, unallocated=200)
        budget = make_budget(
            account, **_SNEAKERS, stored={"last_funded_on": date(2026, 2, 28)}
        )

        report = funding_svc.fund_account(account, today, system_user)

        check.equal(report.transfers, 1, "one transfer")
        check.equal(report.warnings, [], "no warnings")
        budget.refresh_from_db()
        check.equal(budget.last_funded_on, today, "pointer advanced")
        check.equal(budget.balance, Money(50, "USD"), "budget funded")
        unallocated = account.unallocated_budget
        assert unallocated is not None
        unallocated.refresh_from_db()
        check.equal(unallocated.balance, Money(150, "USD"), "from unallocated")

    ####################################################################
    #
    def test_target_date_spreads_gap_over_remaining_occurrences(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
        system_user: User,
    ) -> None:
        """
        GIVEN: a GOAL budget with TARGET_DATE, gap=$300, 3 monthly events left
        WHEN:  fund_account fires on the first event
        THEN:  $100 is transferred ($300 / 3 remaining)
        """
        today = date(2026, 1, 1)
        account = make_account(posted_through=today, unallocated=500)
        budget = make_budget(
            account,
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.TARGET_DATE,
            target_balance=Money(300, "USD"),
            target_date=date(2026, 3, 1),
            funding_schedule=_MONTHLY,
            stored={"last_funded_on": date(2025, 12, 31)},
        )

        report = funding_svc.fund_account(account, today, system_user)

        check.equal(report.transfers, 1, "one transfer")
        budget.refresh_from_db()
        # 3 occurrences: Jan 1, Feb 1, Mar 1 -> $300 / 3 = $100
        check.equal(budget.balance, Money(100, "USD"), "a third of the gap")

    ####################################################################
    #
    def test_target_date_prespent_goal_funds_remaining_gap(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
        system_user: User,
    ) -> None:
        """
        GIVEN: a pre-spent TARGET_DATE Goal on a semi-monthly funding
               schedule, matching a goal budget we saw: target $6,700 by
               Aug 1, $5,602 funded so far, $2,053.02 spent, so two
               funding events remain (Jul 15 and Jul 31) to close a
               $1,098 gap
        WHEN:  fund_account fires on the Jul 15 event
        THEN:  $549 is transferred ($1,098 / 2 remaining events) --
               spending out of the goal must not widen the gap, and no
               extra event may be counted (either error would skew the
               deposit and strand the goal off-target at its deadline)
        """
        today = date(2026, 7, 15)
        account = make_account(posted_through=today, unallocated=2000)
        budget = make_budget(
            account,
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.TARGET_DATE,
            target_balance=Money(Decimal("6700.00"), "USD"),
            target_date=date(2026, 8, 1),
            funding_schedule=_TWICE_MONTHLY_15_EOM,
            stored={
                "balance": Money(Decimal("3548.98"), "USD"),
                "funded_amount": Money(Decimal("5602.00"), "USD"),
                "last_funded_on": date(2026, 6, 30),
            },
        )

        report = funding_svc.fund_account(account, today, system_user)

        check.equal(report.transfers, 1, "one transfer")
        budget.refresh_from_db()
        check.equal(budget.last_funded_on, today, "pointer advanced")
        check.equal(
            budget.balance, Money(Decimal("4097.98"), "USD"), "balance + $549"
        )
        check.equal(
            budget.funded_amount,
            Money(Decimal("6151.00"), "USD"),
            "funded_amount + $549",
        )
        unallocated = account.unallocated_budget
        assert unallocated is not None
        unallocated.refresh_from_db()
        check.equal(
            unallocated.balance,
            Money(Decimal("1451.00"), "USD"),
            "from unallocated",
        )


########################################################################
########################################################################
#
class TestFundingEngineRecurringWithFillup:
    """Recurring budget: fund into fill-up, recur into recurring."""

    ####################################################################
    #
    def test_fund_event_goes_into_fillup_goal(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
        system_user: User,
    ) -> None:
        """
        GIVEN: RECURRING budget, funding schedule monthly
        WHEN:  fund event fires
        THEN:  money moves unallocated -> fillup_goal (not recurring budget)
        """
        today = date(2026, 2, 1)
        account = make_account(posted_through=today, unallocated=200)
        recurring = make_budget(
            account,
            budget_type=Budget.BudgetType.RECURRING,
            funding_type=Budget.FundingType.TARGET_DATE,
            target_balance=Money(80, "USD"),
            funding_schedule=_MONTHLY,
            stored={"last_funded_on": date(2026, 1, 31)},
        )
        fillup = recurring.fillup_goal
        assert fillup is not None

        report = funding_svc.fund_account(account, today, system_user)

        check.equal(report.transfers, 1, "one transfer")
        recurring.refresh_from_db()
        fillup.refresh_from_db()
        check.equal(fillup.balance, Money(80, "USD"), "money lands in fill-up")
        check.equal(
            recurring.balance, Money(0, "USD"), "not the recurring budget"
        )

    ####################################################################
    #
    def test_recur_event_drains_fillup_into_recurring(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
        system_user: User,
    ) -> None:
        """
        GIVEN: fillup has $80, recurring target=$100, balance=$0, recur fires
        WHEN:  recur event processed
        THEN:  $80 moves fillup -> recurring; warning for underfunded;
               last_recurrence_on advances
        """
        today = date(2026, 2, 1)
        account = make_account(posted_through=today)
        # Fill-up capped at its $80 so the fund event sees a zero gap
        # and does not add to it before the recur fires.
        recurring = make_budget(
            account,
            **_BILLS,
            fillup={
                "balance": Money(80, "USD"),
                "target_balance": Money(80, "USD"),
            },
            stored={
                "last_funded_on": today,
                "last_recurrence_on": date(2026, 1, 31),
            },
        )
        fillup = recurring.fillup_goal
        assert fillup is not None

        report = funding_svc.fund_account(account, today, system_user)

        check.equal(report.transfers, 1, "one transfer")
        check.equal(len(report.warnings), 1, "one warning")
        check.is_in("underfunded", "".join(report.warnings), "underfunded")
        recurring.refresh_from_db()
        fillup.refresh_from_db()
        check.equal(recurring.balance, Money(80, "USD"), "recurring gets $80")
        check.equal(fillup.balance, Money(0, "USD"), "fill-up drained")
        check.equal(recurring.last_recurrence_on, today, "pointer advanced")

    ####################################################################
    #
    def test_same_date_fund_before_recur_ordering(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
        system_user: User,
    ) -> None:
        """
        GIVEN: RECURRING budget; fund and recur both on
               the same date
        WHEN:  fund_account processes both events
        THEN:  fund fires first (money hits fillup), then recur (fillup ->
               recurring); ordering produces correct final balances
        """
        today = date(2026, 2, 1)
        account = make_account(posted_through=today, unallocated=200)
        recurring = make_budget(
            account,
            **_BILLS,
            stored={
                "last_funded_on": date(2026, 1, 31),
                "last_recurrence_on": date(2026, 1, 31),
            },
        )
        fillup = recurring.fillup_goal
        assert fillup is not None

        report = funding_svc.fund_account(account, today, system_user)

        check.equal(report.transfers, 2, "two transfers")
        check.equal(report.warnings, [], "no warnings")
        recurring.refresh_from_db()
        fillup.refresh_from_db()
        check.equal(recurring.balance, Money(100, "USD"), "recurring full")
        check.equal(fillup.balance, Money(0, "USD"), "fill-up passed it on")


########################################################################
########################################################################
#
class TestFundingEngineMultiPeriodCatchup:
    """Multi-period backlog processed in date-grouped order."""

    ####################################################################
    #
    def test_three_missed_cycles_processed_in_order(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
        system_user: User,
    ) -> None:
        """
        GIVEN: GOAL budget missed 3 monthly funding events
        WHEN:  fund_account runs with today = 3 months later
        THEN:  3 transfers happen; last_funded_on = latest event date
        """
        # today=Mar 15: window captures Jan 1, Feb 1, Mar 1 (3 events only)
        today = date(2026, 3, 15)
        account = make_account(posted_through=today, unallocated=600)
        # Last funded Dec 31 -- missed Jan 1, Feb 1, Mar 1 events
        budget = make_budget(
            account,
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(1000, "USD"),
            funding_amount=Money(100, "USD"),
            funding_schedule=_MONTHLY,
            stored={"last_funded_on": date(2025, 12, 31)},
        )

        report = funding_svc.fund_account(account, today, system_user)

        check.equal(report.transfers, 3, "three transfers")
        check.equal(report.occurrences_completed, 3, "three completed")
        budget.refresh_from_db()
        check.equal(budget.last_funded_on, date(2026, 3, 1), "latest event")
        check.equal(budget.balance, Money(300, "USD"), "three fundings")
        occurrences = FundingEventOccurrence.objects.filter(
            budget=budget, kind=EventKind.FUND.value
        ).order_by("scheduled_date")
        check.equal(
            [(o.scheduled_date, o.status) for o in occurrences],
            [
                (date(2026, 1, 1), FundingEventOccurrence.Status.COMPLETE),
                (date(2026, 2, 1), FundingEventOccurrence.Status.COMPLETE),
                (date(2026, 3, 1), FundingEventOccurrence.Status.COMPLETE),
            ],
            "each catch-up date has a COMPLETE occurrence",
        )


########################################################################
########################################################################
#
class TestCapAndWarn:
    """Unallocated balance does not block or cap funding."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "budget_type,initial_balance,target,funding_amount,"
        "initial_unallocated,expected_balance,expected_unallocated",
        [
            # Goal: the full $50 transfers although Unallocated holds $20.
            pytest.param("G", 0, 100, 50, 20, 50, -30, id="goal"),
            # Capped: B_0=10, intended=min(20, max(0, 50-10))=20; the
            # full $20 transfers although Unallocated holds $5.
            pytest.param("C", 10, 50, 20, 5, 30, -15, id="capped"),
        ],
    )
    def test_fund_event_completes_when_unallocated_insufficient(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
        system_user: User,
        budget_type: str,
        initial_balance: int,
        target: int,
        funding_amount: int,
        initial_unallocated: int,
        expected_balance: int,
        expected_unallocated: int,
    ) -> None:
        """
        GIVEN: a fund event is due; Unallocated holds less than the
               intended amount
        WHEN:  fund_account runs, then runs again the same day
        THEN:  the first run transfers the full intended amount in one
               pass: Unallocated goes negative, the occurrence is
               COMPLETE and the pointer advances, with no warning;
               the same-day re-run is a no-op (already_moved == intended)
               and leaves exactly one system transfer
        """
        today = date(2026, 3, 1)
        account = make_account(
            posted_through=today, unallocated=initial_unallocated
        )
        budget = make_budget(
            account,
            budget_type=budget_type,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(target, "USD"),
            funding_amount=Money(funding_amount, "USD"),
            funding_schedule=_MONTHLY,
            stored={
                "balance": Money(initial_balance, "USD"),
                "last_funded_on": date(2026, 2, 28),
            },
        )

        first = funding_svc.fund_account(account, today, system_user)

        check.equal(
            (
                first.transfers,
                first.occurrences_completed,
                first.occurrences_partial,
                first.warnings,
            ),
            (1, 1, 0, []),
            "first run: one complete transfer, no warnings",
        )
        budget.refresh_from_db()
        check.equal(
            budget.balance, Money(expected_balance, "USD"), "budget funded"
        )
        check.equal(budget.last_funded_on, today, "pointer advanced")
        unallocated = account.unallocated_budget
        assert unallocated is not None
        unallocated.refresh_from_db()
        check.equal(
            unallocated.balance,
            Money(expected_unallocated, "USD"),
            "unallocated went negative",
        )
        occurrence = FundingEventOccurrence.objects.get(
            budget=budget, kind=EventKind.FUND.value, scheduled_date=today
        )
        check.equal(
            occurrence.status,
            FundingEventOccurrence.Status.COMPLETE,
            "occurrence COMPLETE",
        )
        check.is_not_none(occurrence.completed_at, "and records when")

        rerun = funding_svc.fund_account(account, today, system_user)

        check.equal(
            (
                rerun.transfers,
                rerun.occurrences_completed,
                rerun.occurrences_partial,
            ),
            (0, 0, 0),
            "same-day re-run is a no-op",
        )
        budget.refresh_from_db()
        check.equal(
            budget.balance,
            Money(expected_balance, "USD"),
            "balance unchanged by the re-run",
        )
        check.equal(
            InternalTransaction.objects.filter(
                bank_account=account, dst_budget=budget
            ).count(),
            1,
            "exactly one transfer in total",
        )

    ####################################################################
    #
    def test_empty_fillup_advances_recur_pointer_and_warns(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
        system_user: User,
    ) -> None:
        """
        GIVEN: fillup=$0, recurring recur event fires
        WHEN:  recur event processed
        THEN:  no transfer; warning logged; last_recurrence_on advances to today
               (pointer advances unconditionally -- the missed funding is lost;
               same-day re-runs will retry once fill-up has funds)
        """
        today = date(2026, 2, 1)
        account = make_account(posted_through=today)
        # Fill-up at $0 with a $0 target, so the fund event sees no gap.
        recurring = make_budget(
            account,
            **_BILLS,
            fillup={
                "balance": Money(0, "USD"),
                "target_balance": Money(0, "USD"),
            },
            stored={
                "last_funded_on": today,
                "last_recurrence_on": date(2026, 1, 31),
            },
        )

        report = funding_svc.fund_account(account, today, system_user)

        check.equal(report.transfers, 0, "no transfer")
        check.equal(len(report.warnings), 1, "one warning")
        check.is_in(
            "fill-up goal is empty", "".join(report.warnings), "names why"
        )
        recurring.refresh_from_db()
        check.equal(recurring.last_recurrence_on, today, "pointer advanced")


########################################################################
########################################################################
#
class TestGoalCompletion:
    """Goal budgets: complete=True when target hit; sticky; not re-funded."""

    ####################################################################
    #
    def test_goal_marked_complete_when_target_reached(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
        system_user: User,
    ) -> None:
        """
        GIVEN: GOAL budget balance=$250, target=$300, funding=$50
        WHEN:  fund event fires
        THEN:  balance=$300; complete=True
        """
        today = date(2026, 3, 1)
        account = make_account(posted_through=today, unallocated=200)
        budget = make_budget(
            account,
            **_SNEAKERS,
            stored={
                "balance": Money(250, "USD"),
                "funded_amount": Money(250, "USD"),
                "last_funded_on": date(2026, 2, 28),
            },
        )

        funding_svc.fund_account(account, today, system_user)

        budget.refresh_from_db()
        check.equal(budget.balance, Money(300, "USD"), "reached target")
        check.is_true(budget.complete, "marked complete")

    ####################################################################
    #
    @pytest.mark.parametrize(
        "today,last_funded_on,balance",
        [
            pytest.param(
                date(2026, 3, 1), date(2026, 2, 28), 300, id="at_target"
            ),
            # Completed in March, then $100 spent in April: below target
            # but the latch holds.
            pytest.param(
                date(2026, 4, 1),
                date(2026, 3, 1),
                200,
                id="spent_below_target",
            ),
        ],
    )
    def test_complete_goal_not_funded_again(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
        system_user: User,
        today: date,
        last_funded_on: date,
        balance: int,
    ) -> None:
        """
        GIVEN: a GOAL budget already marked complete, at its target or
               spent below it
        WHEN:  fund_account runs on the next event
        THEN:  no transfer; complete stays True; the balance is unchanged
        """
        account = make_account(posted_through=today, unallocated=200)
        budget = make_budget(
            account,
            **_SNEAKERS,
            stored={
                "balance": Money(balance, "USD"),
                "complete": True,
                "last_funded_on": last_funded_on,
            },
        )

        report = funding_svc.fund_account(account, today, system_user)

        check.equal(report.transfers, 0, "no transfer")
        budget.refresh_from_db()
        check.is_true(budget.complete, "still complete")
        check.equal(budget.balance, Money(balance, "USD"), "balance unchanged")


########################################################################
########################################################################
#
class TestPausedAndArchived:
    """Paused / archived budgets are skipped."""

    ####################################################################
    #
    def test_paused_budget_skipped(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
        system_user: User,
    ) -> None:
        """
        GIVEN: one paused budget and one active budget, both due
        WHEN:  fund_account runs
        THEN:  only the active budget is funded; the paused name appears
               in report.skipped_budgets; the paused budget's occurrence
               is SKIPPED and last_funded_on stays at its prior value (so
               the event is recorded as missed, not consumed)
        """
        today = date(2026, 3, 1)
        prior = date(2026, 2, 28)
        account = make_account(posted_through=today, unallocated=200)
        make_budget(
            account,
            **_SNEAKERS,
            name="Active",
            stored={"last_funded_on": prior},
        )
        paused = make_budget(
            account,
            **_SNEAKERS,
            name="Paused",
            paused=True,
            stored={"last_funded_on": prior},
        )

        report = funding_svc.fund_account(account, today, system_user)

        check.equal(report.transfers, 1, "only the active budget funded")
        check.equal(
            report.skipped_budgets, ["Paused"], "only the paused one skipped"
        )
        paused.refresh_from_db()
        check.equal(paused.balance, Money(0, "USD"), "paused not funded")
        check.equal(paused.last_funded_on, prior, "pointer not consumed")
        occurrence = FundingEventOccurrence.objects.get(
            budget=paused, kind=EventKind.FUND.value, scheduled_date=today
        )
        check.equal(
            occurrence.status,
            FundingEventOccurrence.Status.SKIPPED,
            "occurrence SKIPPED",
        )

    ####################################################################
    #
    def test_archived_budget_skipped(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
        system_user: User,
    ) -> None:
        """
        GIVEN: an archived budget with a due funding event
        WHEN:  fund_account runs
        THEN:  no transfer for the archived budget
        """
        today = date(2026, 3, 1)
        account = make_account(posted_through=today, unallocated=200)
        budget = make_budget(
            account,
            **_SNEAKERS,
            archived=True,
            stored={"last_funded_on": date(2026, 2, 28)},
        )

        report = funding_svc.fund_account(account, today, system_user)

        check.equal(report.transfers, 0, "no transfer")
        budget.refresh_from_db()
        check.equal(budget.balance, Money(0, "USD"), "not funded")


########################################################################
########################################################################
#
class TestOccurrenceSupersession:
    """Newer occurrence closes prior PENDING/PARTIAL as SKIPPED.

    When fund_account processes a new event date, _close_prior_incomplete
    marks any earlier-dated PENDING or PARTIAL occurrence for the same
    (budget, kind) as SKIPPED before the newer event is processed.
    """

    ####################################################################
    #
    @pytest.mark.parametrize(
        "initial_status",
        [
            pytest.param(
                FundingEventOccurrence.Status.PENDING,
                id="pending-superseded",
            ),
            pytest.param(
                FundingEventOccurrence.Status.PARTIAL,
                id="partial-superseded",
            ),
        ],
    )
    def test_newer_occurrence_closes_prior_incomplete_as_skipped(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
        funding_event_occurrence_factory: Callable[..., FundingEventOccurrence],
        system_user: User,
        initial_status: str,
    ) -> None:
        """
        GIVEN: a stale PENDING or PARTIAL occurrence for Jan 1 in the DB,
               and last_funded_on set to Jan 1 so _collect_events only
               sees Feb 1 as due
        WHEN:  fund_account runs for Feb 1 with sufficient funds
        THEN:  _close_prior_incomplete marks Jan 1 as SKIPPED;
               Feb 1 occurrence is COMPLETE; one transfer is made
        """
        jan_1 = date(2026, 1, 1)
        today = date(2026, 2, 1)
        account = make_account(posted_through=today, unallocated=200)
        # The pointer is past Jan 1 so _collect_events only sees Feb 1.
        # The stale occurrence simulates a run that created the
        # occurrence but never settled it (e.g. a crash between writing
        # the occurrence and committing the pointer update).
        budget = make_budget(
            account,
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(1000, "USD"),
            funding_amount=Money(50, "USD"),
            funding_schedule=_MONTHLY,
            stored={"last_funded_on": jan_1},
        )
        funding_event_occurrence_factory(
            budget=budget,
            kind=EventKind.FUND.value,
            scheduled_date=jan_1,
            status=initial_status,
        )

        report = funding_svc.fund_account(account, today, system_user)

        statuses = dict(
            FundingEventOccurrence.objects.filter(budget=budget).values_list(
                "scheduled_date", "status"
            )
        )
        check.equal(
            statuses,
            {
                jan_1: FundingEventOccurrence.Status.SKIPPED,
                today: FundingEventOccurrence.Status.COMPLETE,
            },
            "Jan 1 superseded, Feb 1 completed",
        )
        check.equal(report.transfers, 1, "one transfer")
        check.equal(report.occurrences_completed, 1, "one completed")


########################################################################
########################################################################
#
class TestSameDayRerun:
    """Same-day re-run semantics: already_moved prevents double-counting.

    The engine always processes today's scheduled events regardless of the
    last_funded_on / last_recurrence_on pointer position.  A first run
    always completes the full intended transfer.  A same-day re-run
    computes already_moved from system ITXs already issued for today and
    transfers only the remaining gap -- zero when the first run succeeded.
    The fund-event re-run is covered by
    `TestCapAndWarn::test_fund_event_completes_when_unallocated_insufficient`.
    """

    ####################################################################
    #
    def test_recur_event_is_one_shot_even_when_underfunded(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
        system_user: User,
        user: User,
    ) -> None:
        """
        GIVEN: recur event fires; fill-up ($120) is below target ($200);
               first run sweeps fill-up into Recurring leaving it short
        WHEN:  fund_account re-runs on the same day after the user
               manually tops up the fill-up
        THEN:  the occurrence is already COMPLETE -- RECUR is one-shot --
               so the second run is a no-op and the extra $80 stays in
               the fill-up.  Money that lands after the recur boundary
               waits for the next cycle.
        """
        today = date(2026, 2, 1)
        account = make_account(posted_through=today)
        # Fill-up capped at its $120 so the fund event sees no gap and
        # does not add to the fill-up before the recur fires.
        recurring = make_budget(
            account,
            budget_type=Budget.BudgetType.RECURRING,
            funding_type=Budget.FundingType.TARGET_DATE,
            target_balance=Money(200, "USD"),
            funding_schedule=_MONTHLY,
            recurrence_schedule=_MONTHLY_FIRST,
            fillup={
                "balance": Money(120, "USD"),
                "target_balance": Money(120, "USD"),
            },
            stored={
                "last_funded_on": today,
                "last_recurrence_on": date(2026, 1, 31),
            },
        )
        fillup = recurring.fillup_goal
        assert fillup is not None

        first = funding_svc.fund_account(account, today, system_user)

        assert first.transfers == 1
        assert any("underfunded" in w for w in first.warnings)
        recurring.refresh_from_db()
        fillup.refresh_from_db()
        assert (recurring.balance, fillup.balance) == (
            Money(120, "USD"),
            Money(0, "USD"),
        )
        assert recurring.last_recurrence_on == today
        # Even after a partial sweep the occurrence is COMPLETE -- the
        # design treats the cycle boundary as a hard break.
        assert (
            FundingEventOccurrence.objects.get(
                budget=recurring,
                kind=EventKind.RECUR.value,
                scheduled_date=today,
            ).status
            == FundingEventOccurrence.Status.COMPLETE
        )

        # The user moves $80 into the fill-up from a savings budget after
        # the boundary has passed.
        savings = make_budget(
            account,
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(500, "USD"),
            funding_amount=Money(0, "USD"),
            funding_schedule=_MONTHLY,
            stored={"balance": Money(80, "USD")},
        )
        internal_transaction_svc.create(
            bank_account=account,
            src_budget=savings,
            dst_budget=fillup,
            amount=Money(80, "USD"),
            actor=user,
        )

        rerun = funding_svc.fund_account(account, today, system_user)

        check.equal(rerun.transfers, 0, "re-run moves nothing")
        recurring.refresh_from_db()
        fillup.refresh_from_db()
        check.equal(recurring.balance, Money(120, "USD"), "recurring as was")
        check.equal(fillup.balance, Money(80, "USD"), "top-up waits in fill-up")

    ####################################################################
    #
    def test_manual_itx_not_counted_in_already_moved(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
        system_user: User,
        user: User,
    ) -> None:
        """
        GIVEN: first run transfers the full $100 intended (COMPLETE);
               user manually moves $30 from a savings budget into the Goal
               (non-system ITX, actor=user, no system_event_kind);
               fund_account re-runs on the same day
        WHEN:  second run processes the same fund event
        THEN:  second run is a no-op; already_moved==$100 covers the full
               intended amount; the manual $30 ITX is not counted in
               already_moved; total system transfers = $100 = intended
        """
        today = date(2026, 3, 1)
        account = make_account(posted_through=today, unallocated=60)
        goal = make_budget(
            account,
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(200, "USD"),
            funding_amount=Money(100, "USD"),
            funding_schedule=_MONTHLY,
            stored={"last_funded_on": date(2026, 2, 28)},
        )
        savings = make_budget(
            account,
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(500, "USD"),
            funding_amount=Money(0, "USD"),
            funding_schedule=_MONTHLY,
            stored={"balance": Money(80, "USD")},
        )

        first = funding_svc.fund_account(account, today, system_user)

        assert first.transfers == 1
        goal.refresh_from_db()
        assert goal.balance == Money(100, "USD")

        # Manual user ITX: savings -> goal, $30.  No system_event_kind set.
        internal_transaction_svc.create(
            bank_account=account,
            src_budget=savings,
            dst_budget=goal,
            amount=Money(30, "USD"),
            actor=user,
        )

        rerun = funding_svc.fund_account(account, today, system_user)

        check.equal(rerun.transfers, 0, "re-run moves nothing")
        goal.refresh_from_db()
        check.equal(goal.balance, Money(130, "USD"), "manual $30 kept")
        system_itxs = InternalTransaction.objects.filter(
            bank_account=account,
            dst_budget=goal,
            system_event_kind=InternalTransaction.SystemEventKind.FUND,
        )
        check.equal(
            sum(itx.amount.amount for itx in system_itxs),
            Decimal("100"),
            "system transfers total the intended $100",
        )


########################################################################
########################################################################
#
class TestGoalScenarios:
    """Scenario matrix for Goal budgets (spec section 16, scenarios 4 and 6)."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "target,balance,funded,expected",
        [
            # Spending debited balance to $50 but funded_amount stays
            # $100: transfer = (300 - 100) / 2 = $100 (using balance
            # would give (300 - 50) / 2 = $125).
            pytest.param(300, 50, 100, 100, id="spending_ignored"),
            # $100 funded, then $50 moved out by a manual ITX, lowering
            # funded_amount: transfer = (200 - 50) / 2 = $75 -- the
            # per-event amount rises to close the larger gap.
            pytest.param(200, 50, 50, 75, id="itx_out_raises_amount"),
        ],
    )
    def test_target_date_gap_measured_on_funded_amount(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
        system_user: User,
        target: int,
        balance: int,
        funded: int,
        expected: int,
    ) -> None:
        """
        GIVEN: a TARGET_DATE Goal with 2 fund events left (Feb 1, Mar 1)
               whose balance and funded_amount have diverged
        WHEN:  fund_account runs on Feb 1
        THEN:  the transfer spreads (target - funded_amount) over the
               remaining events; both balance and funded_amount grow by
               that amount
        """
        today = date(2026, 2, 1)
        account = make_account(posted_through=today, unallocated=200)
        budget = make_budget(
            account,
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.TARGET_DATE,
            target_balance=Money(target, "USD"),
            target_date=date(2026, 3, 1),
            funding_schedule=_MONTHLY,
            stored={
                "balance": Money(balance, "USD"),
                "funded_amount": Money(funded, "USD"),
                "last_funded_on": date(2026, 1, 31),
            },
        )

        report = funding_svc.fund_account(account, today, system_user)

        check.equal(report.transfers, 1, "one transfer")
        budget.refresh_from_db()
        check.equal(budget.balance, Money(balance + expected, "USD"), "balance")
        check.equal(
            budget.funded_amount,
            Money(funded + expected, "USD"),
            "funded_amount",
        )


########################################################################
########################################################################
#
class TestCappedScenarios:
    """Scenario matrix for Capped budgets (spec section 16, scenario 1)."""

    ####################################################################
    #
    def test_fund_spend_refund_cycle(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
        system_user: User,
    ) -> None:
        """
        GIVEN: Capped budget; target=$100; funding_amount=$50; balance=$70;
               Unallocated=$200; monthly fund events on the 1st
        WHEN:  fund_account runs on 2026-03-01
        THEN:  B_0=$70; intended=min($50, max(0,$100-$70))=$30;
               transfer=$30; balance=$100
        GIVEN: user spends $30 (balance drops to $70)
        WHEN:  fund_account runs on 2026-04-01
        THEN:  B_0=$70; intended=$30; transfer=$30; balance=$100 again --
               Capped budgets have no completion latch; spending re-opens
               the gap and the next event refunds automatically
        """
        account = make_account(posted_through=date(2026, 3, 1), unallocated=200)
        budget = make_budget(
            account,
            budget_type=Budget.BudgetType.CAPPED,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(100, "USD"),
            funding_amount=Money(50, "USD"),
            funding_schedule=_MONTHLY,
            stored={
                "balance": Money(70, "USD"),
                "last_funded_on": date(2026, 2, 28),
            },
        )

        # First event (Mar 1): B_0=70, intended=min(50, max(0,100-70))=30
        first = funding_svc.fund_account(account, date(2026, 3, 1), system_user)

        assert first.transfers == 1
        budget.refresh_from_db()
        assert budget.balance == Money(100, "USD")
        assert budget.last_funded_on == date(2026, 3, 1)

        # The user spends $30; the account is imported through Apr 1.
        Budget.objects.filter(pkid=budget.pkid).update(balance=Money(70, "USD"))
        BankAccount.objects.filter(pkid=account.pkid).update(
            last_posted_through=date(2026, 4, 1)
        )
        account.refresh_from_db()

        # Second event (Apr 1): B_0=70, intended=min(50, max(0,100-70))=30
        second = funding_svc.fund_account(
            account, date(2026, 4, 1), system_user
        )

        check.equal(second.transfers, 1, "refunded")
        budget.refresh_from_db()
        check.equal(budget.balance, Money(100, "USD"), "back at the cap")
        check.equal(budget.last_funded_on, date(2026, 4, 1), "pointer")


########################################################################
########################################################################
#
class TestRecurringScenarios:
    """Scenario matrix for Recurring budgets (spec section 16, scenarios 3 and 6)."""

    ####################################################################
    #
    def test_recur_shortfall_no_retry_next_day(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
        system_user: User,
    ) -> None:
        """
        GIVEN: RECURRING budget; target=$100; fill-up balance=$30;
               recur event due on 2026-02-01; fund event already marked
               done (last_funded_on=today) so only the recur event fires
        WHEN:  fund_account runs on 2026-02-01
        THEN:  $30 transferred (all fill-up available); underfunded warning;
               last_recurrence_on=2026-02-01
        GIVEN: user does NOT top up the fill-up
        WHEN:  fund_account runs on 2026-02-02
        THEN:  0 transfers -- last_recurrence_on already covers Feb 1 and
               no recur event falls on Feb 2; the $70 shortfall is not
               retried (contrast with a same-day re-run, which would retry)
        """
        today = date(2026, 2, 1)
        tomorrow = date(2026, 2, 2)
        account = make_account(posted_through=tomorrow)
        recurring = make_budget(
            account,
            budget_type=Budget.BudgetType.RECURRING,
            funding_type=Budget.FundingType.TARGET_DATE,
            target_balance=Money(100, "USD"),
            funding_schedule=_MONTHLY,
            recurrence_schedule=_MONTHLY_FIRST,
            fillup={
                "balance": Money(30, "USD"),
                "target_balance": Money(30, "USD"),
            },
            stored={
                "last_funded_on": today,
                "last_recurrence_on": date(2026, 1, 31),
            },
        )

        # First run (Feb 1): recur fires; underfunded but COMPLETE (one-shot).
        first = funding_svc.fund_account(account, today, system_user)

        assert first.transfers == 1
        recurring.refresh_from_db()
        assert recurring.balance == Money(30, "USD")
        assert recurring.last_recurrence_on == today

        # Next day run: no retry of the under-funded recur event.
        next_day = funding_svc.fund_account(account, tomorrow, system_user)

        check.equal(next_day.transfers, 0, "no retry")
        recurring.refresh_from_db()
        check.equal(recurring.balance, Money(30, "USD"), "balance unchanged")

    ####################################################################
    #
    @pytest.mark.parametrize(
        "budget_kwargs",
        [
            # Goals fund a fixed amount.
            pytest.param(
                {
                    "budget_type": Budget.BudgetType.GOAL,
                    "funding_type": Budget.FundingType.FIXED_AMOUNT,
                    "funding_amount": Money(50, "USD"),
                },
                id="goal",
            ),
            # Recurring budgets require TARGET_DATE.
            pytest.param(
                {
                    "budget_type": Budget.BudgetType.RECURRING,
                    "funding_type": Budget.FundingType.TARGET_DATE,
                    "recurrence_schedule": _MONTHLY_FIRST,
                },
                id="recurring",
            ),
        ],
    )
    def test_unpause_resets_pointer_and_next_event_fires(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
        system_user: User,
        budget_kwargs: dict[str, Any],
    ) -> None:
        """
        GIVEN: a paused budget; last_funded_on=2026-02-28;
               fund_account ran on 2026-03-01 while paused
               (occurrence created as SKIPPED; 0 transfers; pointer
               stays at Feb 28 because nothing reached COMPLETE)
        WHEN:  budget unpaused via budget_svc.update on 2026-03-15
               (budget_svc.update resets last_funded_on to Mar 14 = today-1
               so events that fell during the pause are dropped without
               replay)
        AND    fund_account runs on 2026-04-01
        THEN:  Apr 1 fund event fires; money transferred; last_funded_on=Apr 1
        """
        # Enough to cover both cases: the Goal wants $50 and the
        # Recurring budget prorates to up to $300 per event, which must
        # fully clear so last_funded_on actually advances.
        account = make_account(posted_through=date(2026, 4, 1), unallocated=500)
        budget = make_budget(
            account,
            name="Savings",
            target_balance=Money(300, "USD"),
            funding_schedule=_MONTHLY,
            paused=True,
            stored={"last_funded_on": date(2026, 2, 28)},
            **budget_kwargs,
        )

        # Engine runs while paused on Mar 1: no transfer.
        while_paused = funding_svc.fund_account(
            account, date(2026, 3, 1), system_user
        )

        assert while_paused.transfers == 0
        assert "Savings" in while_paused.skipped_budgets
        budget.refresh_from_db()
        # A skipped (paused) event does not advance the pointer -- the
        # SKIPPED row records the event so it is not replayed.
        assert budget.last_funded_on == date(2026, 2, 28)

        # The user unpauses on Mar 15: the pointer resets to Mar 14.
        with freeze_time("2026-03-15"):
            budget, _ = budget_svc.update(budget, paused=False)
        budget.refresh_from_db()
        assert budget.last_funded_on == date(2026, 3, 14)

        # April 1: the next scheduled event fires.
        after_unpause = funding_svc.fund_account(
            account, date(2026, 4, 1), system_user
        )

        check.greater_equal(after_unpause.transfers, 1, "funded again")
        budget.refresh_from_db()
        check.equal(budget.last_funded_on, date(2026, 4, 1), "pointer")


########################################################################
########################################################################
#
class TestScheduleFundingRuns:
    """schedule_funding_runs dispatches workers based on owner local time."""

    ####################################################################
    #
    @pytest.fixture
    def make_owner_account(
        self, bank_account_factory: Callable[..., BankAccount]
    ) -> Callable[..., BankAccount]:
        """Return a factory for accounts whose owner lives in New York.

        Returns:
            A callable `(**kwargs) -> BankAccount`; `kwargs` pass
            through to the account factory.
        """

        def _make(**kwargs: Any) -> BankAccount:
            account = bank_account_factory(**kwargs)
            owner = account.owners.first()
            assert owner is not None
            owner.timezone = _TZ_NY
            owner.save()
            return account

        return _make

    ####################################################################
    #
    @pytest.fixture
    def dispatch(self, mocker: MockerFixture) -> SimpleNamespace:
        """Patch the scheduler's clock and both worker enqueues.

        Returns:
            A namespace with `run(utc_hour, utc_minute)`, which runs
            `schedule_funding_runs` at that time on 2026-05-18 UTC, and
            the `fund` and `recur` `apply_async` mocks.
        """
        clock = mocker.patch("moneypools.tasks.datetime")
        ns = SimpleNamespace(
            fund=mocker.patch("moneypools.tasks.fund_one_account.apply_async"),
            recur=mocker.patch(
                "moneypools.tasks.recur_one_account.apply_async"
            ),
        )

        def _run(utc_hour: int, utc_minute: int) -> None:
            clock.now.return_value = datetime(
                2026, 5, 18, utc_hour, utc_minute, tzinfo=UTC
            )
            schedule_funding_runs()

        ns.run = _run
        return ns

    ####################################################################
    #
    @pytest.mark.parametrize(
        "utc_hour,utc_minute,expect_fund,expect_recur",
        [
            pytest.param(3, 10, True, False, id="fund-window: 23:10 EDT"),
            pytest.param(7, 10, False, True, id="recur-window: 03:10 EDT"),
            pytest.param(12, 0, False, False, id="outside: 08:00 EDT"),
        ],
    )
    def test_schedule_dispatches_correct_task(
        self,
        make_owner_account: Callable[..., BankAccount],
        dispatch: SimpleNamespace,
        utc_hour: int,
        utc_minute: int,
        expect_fund: bool,
        expect_recur: bool,
    ) -> None:
        """
        GIVEN: one account whose owner is in a known timezone
        WHEN:  schedule_funding_runs fires at a specific UTC time
        THEN:  fund_one_account is enqueued iff local time is in [23:00, 23:30)
               recur_one_account is enqueued iff local time is in [03:00, 03:30)
        """
        make_owner_account()

        dispatch.run(utc_hour, utc_minute)

        check.equal(dispatch.fund.called, expect_fund, "fund enqueued")
        check.equal(dispatch.recur.called, expect_recur, "recur enqueued")

    ####################################################################
    #
    def test_schedule_passes_local_date_str(
        self,
        make_owner_account: Callable[..., BankAccount],
        dispatch: SimpleNamespace,
    ) -> None:
        """
        GIVEN: an account in America/New_York, UTC time 03:10 (= 23:10 EDT)
        WHEN:  schedule_funding_runs fires
        THEN:  fund_one_account is called with local_date_str='2026-05-17'
               (the local date, which is one day behind UTC)
        """
        make_owner_account()

        # 03:10 UTC on the 18th = 23:10 EDT on the *17th*
        dispatch.run(3, 10)

        assert dispatch.fund.call_count == 1
        kwargs = dispatch.fund.call_args.kwargs
        assert kwargs["kwargs"]["local_date_str"] == "2026-05-17"

    ####################################################################
    #
    def test_auto_funding_disabled_account_is_not_dispatched(
        self,
        make_owner_account: Callable[..., BankAccount],
        dispatch: SimpleNamespace,
    ) -> None:
        """
        GIVEN: an account with auto_funding_enabled=False
        WHEN:  schedule_funding_runs fires (inside a FUND window)
        THEN:  fund_one_account is not enqueued for that account
        """
        make_owner_account(auto_funding_enabled=False)

        dispatch.run(3, 10)

        assert dispatch.fund.called is False

    ####################################################################
    #
    @pytest.mark.parametrize(
        "task,kind",
        [
            pytest.param(fund_one_account, EventKind.FUND, id="fund"),
            pytest.param(recur_one_account, EventKind.RECUR, id="recur"),
        ],
    )
    def test_worker_runs_fund_account_for_its_kind(
        self,
        bank_account_factory: Callable[..., BankAccount],
        system_user: User,
        mocker: MockerFixture,
        task: Callable[..., Any],
        kind: EventKind,
    ) -> None:
        """
        GIVEN: a valid account and the funding-system user
        WHEN:  fund_one_account or recur_one_account runs with a
               local_date_str
        THEN:  funding_svc.fund_account is called once for that account
               and the parsed local date, as the system user, with only
               the worker's event kind
        """
        account = bank_account_factory()
        fund_account: MagicMock = mocker.patch(
            "moneypools.tasks.funding_svc.fund_account",
            return_value=funding_svc.FundingReport(account_id=str(account.id)),
        )

        task(str(account.id), local_date_str="2026-05-17")

        assert fund_account.call_args_list == [
            call(account, date(2026, 5, 17), system_user, kinds={kind})
        ]


########################################################################
########################################################################
#
class TestMarkImportedEndpoint:
    """POST /api/v1/bank-accounts/<id>/mark-imported/"""

    ####################################################################
    #
    def _url(self, account: BankAccount) -> str:
        return reverse(
            "api_v1:bankaccount-mark-imported", kwargs={"id": str(account.id)}
        )

    ####################################################################
    #
    def test_sets_last_imported_at_and_last_posted_through(
        self, account: BankAccount, auth_client: APIClient
    ) -> None:
        """
        GIVEN: authenticated owner, valid date in body
        WHEN:  POST mark-imported
        THEN:  200; last_imported_at set; last_posted_through=supplied date
        """
        resp = auth_client.post(
            self._url(account),
            {"last_posted_through": "2026-03-15"},
            format="json",
        )

        assert resp.status_code == 200
        account.refresh_from_db()
        check.equal(
            account.last_posted_through, date(2026, 3, 15), "posted through"
        )
        check.is_not_none(account.last_imported_at, "import time recorded")

    ####################################################################
    #
    def test_monotonic_update_never_regresses(
        self, account: BankAccount, auth_client: APIClient
    ) -> None:
        """
        GIVEN: last_posted_through=2026-03-15; POST with older date 2026-03-01
        WHEN:  POST mark-imported
        THEN:  last_posted_through stays 2026-03-15 (not regressed)
        """
        BankAccount.objects.filter(pkid=account.pkid).update(
            last_posted_through=date(2026, 3, 15)
        )

        resp = auth_client.post(
            self._url(account),
            {"last_posted_through": "2026-03-01"},
            format="json",
        )

        assert resp.status_code == 200
        account.refresh_from_db()
        assert account.last_posted_through == date(2026, 3, 15)

    ####################################################################
    #
    def test_requires_authentication(
        self, account: BankAccount, api_client: APIClient
    ) -> None:
        """
        GIVEN: unauthenticated request
        WHEN:  POST mark-imported
        THEN:  401
        """
        resp = api_client.post(
            self._url(account),
            {"last_posted_through": "2026-03-15"},
            format="json",
        )
        assert resp.status_code == 401

    ####################################################################
    #
    def test_rejects_non_owner(
        self,
        account: BankAccount,
        user_factory: Callable[..., User],
        make_auth_client: Callable[[User], APIClient],
    ) -> None:
        """
        GIVEN: authenticated user who does not own the account
        WHEN:  POST mark-imported
        THEN:  404 (ownership filter hides the account)
        """
        resp = make_auth_client(user_factory()).post(
            self._url(account),
            {"last_posted_through": "2026-03-15"},
            format="json",
        )
        assert resp.status_code == 404

    ####################################################################
    #
    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({}, id="missing"),
            pytest.param({"last_posted_through": "not-a-date"}, id="malformed"),
        ],
    )
    def test_validation_errors(
        self, account: BankAccount, auth_client: APIClient, body: dict
    ) -> None:
        """
        GIVEN: missing or malformed last_posted_through
        WHEN:  POST mark-imported
        THEN:  400 with an error on last_posted_through
        """
        resp = auth_client.post(self._url(account), body, format="json")

        assert resp.status_code == 400
        assert "last_posted_through" in resp.data


########################################################################
########################################################################
#
class TestNextFundingInfo:
    """next_funding_info() returns the next scheduled event (or None)."""

    ####################################################################
    #
    def test_fixed_amount_goal(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: GOAL budget with FIXED_AMOUNT funding; last_funded_on in
               prior month
        WHEN:  next_funding_info called
        THEN:  returns the next event date and amount.
        """
        budget = make_budget(
            make_account(),
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            target_balance=Money(1000, "USD"),
            funding_amount=Money(100, "USD"),
            funding_schedule=_MONTHLY,
            stored={"last_funded_on": date(2026, 2, 28)},
        )

        info = funding_svc.next_funding_info(budget, today=date(2026, 3, 1))

        assert info is not None
        check.equal(info.date, date(2026, 3, 1), "next event date")
        check.equal(info.amount, Money(100, "USD"), "fixed amount")

    ####################################################################
    #
    def test_target_date_goal_returns_prorated_amount(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: GOAL budget with TARGET_DATE funding; $300 gap; 3 events left
        WHEN:  next_funding_info called
        THEN:  amount = $100 (gap / remaining)
        """
        today = date(2026, 3, 1)
        budget = make_budget(
            make_account(posted_through=today),
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.TARGET_DATE,
            target_balance=Money(300, "USD"),
            target_date=date(2026, 5, 1),
            funding_schedule=_MONTHLY,
            stored={"last_funded_on": date(2026, 2, 28)},
        )

        info = funding_svc.next_funding_info(budget, today=today)

        assert info is not None
        check.equal(info.date, date(2026, 3, 1), "next event date")
        # $300 gap / 3 remaining months = $100
        check.equal(info.amount, Money(100, "USD"), "a third of the gap")

    ####################################################################
    #
    @pytest.mark.parametrize(
        "budget_kwargs,stored",
        [
            # A CAPPED budget already at its cap: a zero-amount event is
            # suppressed.
            pytest.param(
                {
                    "budget_type": Budget.BudgetType.CAPPED,
                    "funding_type": Budget.FundingType.FIXED_AMOUNT,
                    "target_balance": Money(200, "USD"),
                    "funding_amount": Money(50, "USD"),
                },
                {
                    "balance": Money(200, "USD"),
                    "last_funded_on": date(2026, 2, 28),
                },
                id="capped_at_cap",
            ),
            # Paused and RECURRING budgets return None before any
            # schedule enumeration.
            pytest.param(
                {
                    "budget_type": Budget.BudgetType.GOAL,
                    "funding_type": Budget.FundingType.FIXED_AMOUNT,
                    "target_balance": Money(500, "USD"),
                    "funding_amount": Money(50, "USD"),
                    "paused": True,
                },
                None,
                id="paused",
            ),
            pytest.param(
                {
                    "budget_type": Budget.BudgetType.RECURRING,
                    "funding_type": Budget.FundingType.TARGET_DATE,
                    "target_balance": Money(400, "USD"),
                },
                None,
                id="recurring",
            ),
        ],
    )
    def test_returns_none(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
        budget_kwargs: dict[str, Any],
        stored: dict[str, Any] | None,
    ) -> None:
        """
        GIVEN: a budget with nothing to fund next -- capped at its cap,
               paused, or RECURRING (funded through its fill-up)
        WHEN:  next_funding_info called
        THEN:  returns None
        """
        today = date(2026, 3, 1)
        budget = make_budget(
            make_account(posted_through=today),
            funding_schedule=_MONTHLY,
            stored=stored,
            **budget_kwargs,
        )

        assert funding_svc.next_funding_info(budget, today=today) is None

    ####################################################################
    #
    def test_fillup_goal_returns_next_event(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: RECURRING+with_fillup budget; fill-up goal has a due event
        WHEN:  next_funding_info called on the ASSOCIATED_FILLUP_GOAL child
        THEN:  returns NextFundingInfo using parent's schedule and amount
        """
        today = date(2026, 3, 1)
        parent = make_budget(
            make_account(posted_through=today),
            budget_type=Budget.BudgetType.RECURRING,
            funding_type=Budget.FundingType.TARGET_DATE,
            target_balance=Money(200, "USD"),
            funding_schedule=_MONTHLY,
            stored={"last_funded_on": date(2026, 2, 28)},
        )
        fillup = parent.fillup_goal
        assert fillup is not None

        info = funding_svc.next_funding_info(fillup, today=today)

        assert info is not None
        check.equal(info.date, date(2026, 3, 1), "next event date")
        check.equal(info.amount, Money(200, "USD"), "parent's amount")

    ####################################################################
    #
    def test_never_funded_finds_catchup_event(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: RECURRING+fillup budget that has never been funded
               (last_funded_on=None, created May 1); funding schedule fires on
               the 15th and last day of each month; last_posted_through=April 30;
               today=May 9
        WHEN:  next_funding_info called on the fillup goal
        THEN:  returns date=April 30 (catch-up), not May 15 (next future event)

        Regression: old anchor used created_at.date() directly, so the April 30
        event was skipped and May 15 was returned instead.  Fix: mirror
        _collect_events and use _prev_recurrence_boundary to find the last
        boundary before created_at, then pull back one day.
        """
        # "Never funded, created on May 1": budget_svc.create sets the
        # pointers to created_at - 1 day, so they are nulled and
        # created_at backdated.  _prev_recurrence_boundary(May 1) is
        # April 30, so the first event after April 29 is April 30.
        parent = make_budget(
            make_account(posted_through=date(2026, 4, 30)),
            budget_type=Budget.BudgetType.RECURRING,
            funding_type=Budget.FundingType.TARGET_DATE,
            target_balance=Money(1000, "USD"),
            funding_schedule=_TWICE_MONTHLY_15_EOM,
            recurrence_schedule=_MONTHLY_MAY_FIRST,
            stored={
                "created_at": datetime(2026, 5, 1, tzinfo=UTC),
                "last_funded_on": None,
                "last_recurrence_on": None,
            },
        )
        fillup = parent.fillup_goal
        assert fillup is not None

        info = funding_svc.next_funding_info(fillup, today=date(2026, 5, 9))

        assert info is not None
        assert info.date == date(2026, 4, 30)

    ####################################################################
    #
    def test_yearly_remaining_events_from_today(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: RECURRING+fillup with a yearly recurrence (first reset Sep 15,
               2026) and a twice-monthly funding schedule (DTSTART Jan 15, 2026,
               15th and EOM); budget created Apr 30, last_funded_on=May 8 so
               next event is May 15; last_recurrence_on=None (first cycle)
        WHEN:  next_funding_info called on the fill-up goal
        THEN:  amount = $3400 / 8 = $425 (remaining events May 15 through Sep 15)

        The proration formula uses gap / N_remaining (fund events from event_date
        through cycle_before = Sep 14, inclusive).  With event_date=May 15,
        there are 8 remaining events before the Sep 15 recur boundary:
          May 15, May 31, Jun 15, Jun 30, Jul 15, Jul 31, Aug 15, Aug 31
        The Sep 15 fund event (which fires the same day as the recur boundary)
        is NOT counted here -- it deposits toward the NEXT annual cycle.
        On Sep 15, the recur event closes out the current cycle (sweeps
        fill-up into recurring, capped at the gap), and the fund event begins
        the next cycle (first deposit into the now-swept fill-up).  The
        "fund before recur" sort order has no effect on the boundary day --
        both orderings produce the same final balances because the recur cap
        is based on the recurring budget's gap, not the fill-up balance.
        $3400 / 8 = $425.00
        """
        today = date(2026, 5, 9)
        # last_recurrence_on=None takes the first-cycle code path
        # (budget_svc.create initialises it to created_at - 1 day).
        parent = make_budget(
            make_account(posted_through=today),
            budget_type=Budget.BudgetType.RECURRING,
            funding_type=Budget.FundingType.TARGET_DATE,
            target_balance=Money(3400, "USD"),
            funding_schedule=_TWICE_MONTHLY_15_EOM,
            recurrence_schedule=_YEARLY_SEP_15,
            stored={
                "last_funded_on": date(2026, 5, 8),
                "last_recurrence_on": None,
                "created_at": datetime(2026, 4, 30, tzinfo=UTC),
            },
        )
        fillup = parent.fillup_goal
        assert fillup is not None

        info = funding_svc.next_funding_info(fillup, today=today)

        assert info is not None
        check.equal(info.date, date(2026, 5, 15), "next event")
        check.equal(info.amount, Money("425.00", "USD"), "$3400 / 8")


########################################################################
########################################################################
#
class TestNextRecurrenceDate:
    """next_recurrence_date() returns the upcoming refresh date."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "recurrence_schedule,last_recurrence_on,today,expected",
        [
            # The display bug this function fixes: a monthly budget
            # whose DTSTART (Feb 1) is long past.  The next refresh is
            # derived from the pointer, not from DTSTART.
            pytest.param(
                _MONTHLY_FIRST,
                date(2026, 7, 1),
                date(2026, 7, 3),
                date(2026, 8, 1),
                id="monthly/next_cycle",
            ),
            # Yearly budget refreshed on Jun 15 2026; the next refresh
            # is Jun 15 of the following year.
            pytest.param(
                recurrence.Recurrence(
                    dtstart=datetime(2026, 6, 15),
                    rrules=[recurrence.Rule(recurrence.YEARLY)],
                ),
                date(2026, 6, 15),
                date(2026, 7, 3),
                date(2027, 6, 15),
                id="yearly/next_year",
            ),
            # Every 2 months anchored Mar 1 (Mar, May, Jul, Sep, ...);
            # the interval phase from DTSTART is preserved.
            pytest.param(
                recurrence.Recurrence(
                    dtstart=datetime(2026, 3, 1),
                    rrules=[recurrence.Rule(recurrence.MONTHLY, interval=2)],
                ),
                date(2026, 7, 1),
                date(2026, 7, 3),
                date(2026, 9, 1),
                id="bimonthly/phase_preserved",
            ),
            # Overdue: the Jun 1 event was never processed, so it is
            # still the next one (it will run at the next scheduler
            # pass) even though the date is in the past.
            pytest.param(
                _MONTHLY_FIRST,
                date(2026, 5, 1),
                date(2026, 7, 3),
                date(2026, 6, 1),
                id="monthly/overdue_catchup",
            ),
        ],
    )
    def test_returns_first_unprocessed_occurrence(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
        recurrence_schedule: recurrence.Recurrence,
        last_recurrence_on: date,
        today: date,
        expected: date,
    ) -> None:
        """
        GIVEN: a RECURRING budget with last_recurrence_on set
        WHEN:  next_recurrence_date is called
        THEN:  it returns the first occurrence after last_recurrence_on,
               regardless of the schedule's DTSTART anchor.
        """
        budget = make_budget(
            make_account(),
            budget_type=Budget.BudgetType.RECURRING,
            funding_type=Budget.FundingType.TARGET_DATE,
            target_balance=Money(100, "USD"),
            funding_schedule=_MONTHLY,
            recurrence_schedule=recurrence_schedule,
            stored={"last_recurrence_on": last_recurrence_on},
        )

        assert funding_svc.next_recurrence_date(budget, today=today) == expected

    ####################################################################
    #
    def test_never_processed_uses_creation_anchor(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: a RECURRING budget created before its first cycle
               (DTSTART in the future) with last_recurrence_on=None
        WHEN:  next_recurrence_date is called
        THEN:  it returns the schedule's first occurrence.
        """
        budget = make_budget(
            make_account(),
            budget_type=Budget.BudgetType.RECURRING,
            funding_type=Budget.FundingType.TARGET_DATE,
            target_balance=Money(100, "USD"),
            funding_schedule=_MONTHLY,
            recurrence_schedule=_MONTHLY_MAY_FIRST,
            stored={
                "last_recurrence_on": None,
                "created_at": datetime(2026, 4, 20, tzinfo=UTC),
            },
        )

        result = funding_svc.next_recurrence_date(
            budget, today=date(2026, 4, 25)
        )

        assert result == date(2026, 5, 1)

    ####################################################################
    #
    @pytest.mark.parametrize(
        "budget_type,stored",
        [
            pytest.param(
                Budget.BudgetType.RECURRING, {"paused": True}, id="paused"
            ),
            pytest.param(
                Budget.BudgetType.RECURRING, {"archived": True}, id="archived"
            ),
            pytest.param(
                Budget.BudgetType.RECURRING,
                {"recurrence_schedule": None},
                id="no_schedule",
            ),
            pytest.param(Budget.BudgetType.GOAL, None, id="goal_type"),
        ],
    )
    def test_returns_none_when_not_applicable(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
        budget_type: str,
        stored: dict[str, Any] | None,
    ) -> None:
        """
        GIVEN: a budget that is paused, archived, non-Recurring, or has
               no recurrence_schedule
        WHEN:  next_recurrence_date is called
        THEN:  it returns None.
        """
        budget = make_budget(
            make_account(),
            budget_type=budget_type,
            funding_type=Budget.FundingType.TARGET_DATE,
            target_balance=Money(100, "USD"),
            funding_schedule=_MONTHLY,
            recurrence_schedule=_MONTHLY_FIRST,
            stored=stored,
        )

        result = funding_svc.next_recurrence_date(
            budget, today=date(2026, 7, 3)
        )

        assert result is None


########################################################################
########################################################################
#
class TestFundingPace:
    """funding_pace() -- server-side goal pace, measured on funded_amount.

    Fixture shape mirrors a real pre-spent goal: target $6,700 by Aug 1
    on a 15th/EOM schedule anchored May 15 (6 events total).  Pace must
    track deposits against events elapsed and ignore the balance
    entirely -- spending (even into a negative balance) is not 'behind'.
    """

    ####################################################################
    #
    @pytest.fixture
    def make_goal(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
    ) -> Callable[..., Budget]:
        """Return a factory for the reference goal budget.

        Returns:
            A callable `(with_schedule=True, **stored) -> Budget` creating
            the goal on 2026-05-15, then writing `stored` to it.
        """

        def _make(with_schedule: bool = True, **stored: Any) -> Budget:
            kwargs: dict[str, Any] = {}
            if with_schedule:
                kwargs["funding_schedule"] = recurrence.Recurrence(
                    dtstart=datetime(2026, 5, 15),
                    rrules=[
                        recurrence.Rule(recurrence.MONTHLY, bymonthday=[15, -1])
                    ],
                )
            with freeze_time("2026-05-15"):
                return make_budget(
                    make_account(),
                    name="Trip Abroad",
                    budget_type=Budget.BudgetType.GOAL,
                    funding_type=Budget.FundingType.TARGET_DATE,
                    target_balance=Money(Decimal("6700.00"), "USD"),
                    target_date=date(2026, 8, 1),
                    stored=stored,
                    **kwargs,
                )

        return _make

    ####################################################################
    #
    @pytest.mark.parametrize(
        "with_schedule,funded,today,expected",
        [
            # 4 of 6 events elapsed (expected 66.7%); 83.6% funded --
            # the pre-spent real-world budget that motivated this: its
            # balance is far below target but its deposits are ahead.
            pytest.param(
                True,
                "5602.00",
                date(2026, 7, 11),
                "ahead",
                id="prespent/ahead",
            ),
            # Same point in time, deposits well short of 4/6.
            pytest.param(
                True, "3000.00", date(2026, 7, 11), "behind", id="behind"
            ),
            # Deposits within the 5% band around 4/6.
            pytest.param(
                True,
                "4467.00",
                date(2026, 7, 11),
                "on_track",
                id="on_track",
            ),
            # Past the target date anything short of the target is
            # behind, regardless of the schedule.
            pytest.param(
                True,
                "5602.00",
                date(2026, 8, 2),
                "behind",
                id="past_deadline",
            ),
            # Before the first event nothing is expected yet.
            pytest.param(
                True, "0.00", date(2026, 5, 1), "on_track", id="no_events_yet"
            ),
            # No schedule: falls back to linear time (created May 15,
            # target Aug 1); ~62% elapsed by Jul 3 vs 45% funded.
            pytest.param(
                False,
                "3000.00",
                date(2026, 7, 3),
                "behind",
                id="no_schedule_linear_fallback",
            ),
        ],
    )
    def test_pace_reflects_funded_vs_events_elapsed(
        self,
        with_schedule: bool,
        funded: str,
        today: date,
        expected: str,
        make_goal: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: a Goal budget and a funded_amount at a point in time
        WHEN:  funding_pace is computed
        THEN:  deposits are compared to the fraction of funding events
               elapsed (or linear time without a schedule); the balance
               plays no part
        """
        budget = make_goal(
            with_schedule=with_schedule,
            funded_amount=Money(Decimal(funded), "USD"),
            # A deeply overspent balance must not affect pace.
            balance=Money(Decimal("-100.00"), "USD"),
        )

        assert funding_svc.funding_pace(budget, today=today) == expected

    ####################################################################
    #
    @pytest.mark.parametrize(
        "stored",
        [
            pytest.param(
                # funding_type and target_date flip too: DB constraints
                # require capped budgets to be FIXED_AMOUNT with no
                # target date.
                {
                    "budget_type": Budget.BudgetType.CAPPED,
                    "funding_type": Budget.FundingType.FIXED_AMOUNT,
                    "target_date": None,
                },
                id="non_goal",
            ),
            pytest.param({"paused": True}, id="paused"),
            pytest.param({"archived": True}, id="archived"),
            pytest.param({"complete": True}, id="complete"),
            pytest.param({"target_date": None}, id="no_target_date"),
            pytest.param({"target_balance": Money(0, "USD")}, id="zero_target"),
        ],
    )
    def test_pace_not_applicable_returns_none(
        self,
        stored: dict[str, Any],
        make_goal: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: a budget where pace has no meaning (wrong type, paused,
               archived, complete, or lacking a target/date)
        WHEN:  funding_pace is computed
        THEN:  returns None so clients can distinguish 'not applicable'
               from any pace value
        """
        budget = make_goal(**stored)

        assert funding_svc.funding_pace(budget, today=date(2026, 7, 11)) is None


########################################################################
########################################################################
#
class TestFillAmountProrated:
    """Unit tests for _fill_amount_prorated -- the core proration formula.

    Uses a twice-monthly funding schedule (10th and 20th) inside a monthly
    recurrence cycle (resets on the 1st).  cycle_start and cycle_before are
    passed in directly so these tests are independent of the boundary helpers.

    The formula is gap / N_remaining, where N_remaining = funding events from
    event_date (inclusive) through cycle_before (inclusive).

    Feb cycle, target=$100:
    - Event on Feb 10: N_remaining=2 (Feb 10 + Feb 20), per_event = gap/2
    - Event on Feb 20: N_remaining=1 (Feb 20 only),     per_event = gap/1
    """

    _CYCLE_START = date(2026, 2, 1)
    _CYCLE_BEFORE = date(2026, 2, 28)

    ####################################################################
    #
    @pytest.mark.parametrize(
        "fill_up_balance,event_date,expected",
        [
            pytest.param(
                Money(0, "USD"),
                date(2026, 2, 10),
                Money("50.00", "USD"),
                id="first_event/empty",
            ),
            pytest.param(
                Money(5, "USD"),
                date(2026, 2, 10),
                # gap = 95, N_remaining = 2 -> 95/2 = 47.50
                Money("47.50", "USD"),
                id="first_event/carryover",
            ),
            pytest.param(
                Money("27.50", "USD"),
                date(2026, 2, 20),
                # gap = 72.50, N_remaining = 1 -> 72.50/1 = 72.50
                # (full remaining gap on the last event)
                Money("72.50", "USD"),
                id="last_event/behind",
            ),
            pytest.param(
                Money(95, "USD"),
                date(2026, 2, 20),
                Money("5.00", "USD"),
                id="last_event/nearly_full",
            ),
            # ahead: fill-up already holds $60 of $100; gap=40 split over 2
            # remaining events -> 40/2 = $20 per event (even spread).
            pytest.param(
                Money(60, "USD"),
                date(2026, 2, 10),
                Money("20.00", "USD"),
                id="first_event/ahead_capped_by_gap",
            ),
            pytest.param(
                Money(100, "USD"),
                date(2026, 2, 10),
                Money("0.00", "USD"),
                id="first_event/already_at_target",
            ),
        ],
    )
    def test_prorated_amount(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
        fill_up_balance: Money,
        event_date: date,
        expected: Money,
    ) -> None:
        """
        GIVEN: a $100 Recurring budget whose fill-up goal has a known
               balance at a point in the Feb cycle
        WHEN:  _fill_amount_prorated is called with explicit cycle bounds
        THEN:  the returned amount is gap / N_remaining (remaining events from
               event_date through cycle_before, inclusive on both ends)
        """
        recurring = make_budget(
            make_account(),
            budget_type=Budget.BudgetType.RECURRING,
            funding_type=Budget.FundingType.TARGET_DATE,
            target_balance=Money(100, "USD"),
            funding_schedule=_TWICE_MONTHLY,
            recurrence_schedule=_MONTHLY_FIRST,
            fillup={"balance": fill_up_balance},
        )
        fillup = recurring.fillup_goal
        assert fillup is not None

        amount = _fill_amount_prorated(
            recurring,
            fillup,
            event_date=event_date,
            cycle_start=self._CYCLE_START,
            cycle_before=self._CYCLE_BEFORE,
        )

        assert amount == expected


########################################################################
########################################################################
#
class TestRecurringTargetDateProration:
    """Integration: RECURRING+TARGET_DATE+fill-up goes through _fill_amount_prorated."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "today,last_funded_on,initial_balance,expected_balance",
        [
            pytest.param(
                date(2026, 2, 10),
                date(2026, 1, 31),
                Money(5, "USD"),
                # gap = 95, N_remaining = 2 -> 95/2 = 47.50; fillup: 5 + 47.50 = 52.50
                Money("52.50", "USD"),
                id="first_event",
            ),
            pytest.param(
                date(2026, 2, 20),
                date(2026, 2, 10),
                Money("55.00", "USD"),
                Money("100.00", "USD"),
                id="second_event",
            ),
        ],
    )
    def test_fund_account_prorates_into_fillup(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
        system_user: User,
        today: date,
        last_funded_on: date,
        initial_balance: Money,
        expected_balance: Money,
    ) -> None:
        """
        GIVEN: RECURRING+TARGET_DATE+fillup, 2 events/cycle (Feb 10 and Feb 20)
        WHEN:  fund_account fires at the parametrized event date
        THEN:  fill-up balance increases by gap/N_remaining per event
        """
        account = make_account(posted_through=today, unallocated=500)
        recurring = make_budget(
            account,
            budget_type=Budget.BudgetType.RECURRING,
            funding_type=Budget.FundingType.TARGET_DATE,
            target_balance=Money(100, "USD"),
            funding_schedule=_TWICE_MONTHLY,
            recurrence_schedule=_MONTHLY_FIRST,
            fillup={"balance": initial_balance},
            stored={"last_funded_on": last_funded_on},
        )
        fillup = recurring.fillup_goal
        assert fillup is not None

        report = funding_svc.fund_account(account, today, system_user)

        check.equal(report.transfers, 1, "one transfer")
        fillup.refresh_from_db()
        check.equal(fillup.balance, expected_balance, "prorated deposit")


########################################################################
########################################################################
#
class TestFundingNotifications:
    """Tests that the funding pipeline fires the expected notification kinds."""

    ####################################################################
    #
    def test_funding_complete_notification_context(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: a GOAL budget funded $50/month, unallocated=$200, today=Mar 1
        WHEN:  fund_one_account runs and transfers $50
        THEN:  a FUNDING_COMPLETE notification is created for each account
               owner with account_id, date, funded_budgets, and warnings in
               context; funded_budgets contains all expected keys
        """
        today = date(2026, 3, 1)
        account = make_account(posted_through=today, unallocated=200)
        make_budget(
            account, **_SNEAKERS, stored={"last_funded_on": date(2026, 2, 28)}
        )
        owner = account.owners.first()
        assert owner is not None

        fund_one_account(str(account.id), local_date_str=today.isoformat())

        n = Notification.objects.get(user=owner, kind=FUNDING_COMPLETE)
        check.equal(n.context["account_id"], str(account.id), "account id")
        check.is_true(
            {"account_name", "date", "funded_budgets", "warnings"}
            <= set(n.context),
            "context keys",
        )
        funded = n.context["funded_budgets"]
        assert len(funded) == 1
        check.is_true(
            {
                "budget_id",
                "budget_name",
                "amount_funded",
                "total_funded",
                "balance",
                "target_balance",
                "goal_reached",
                "is_fillup",
            }
            <= set(funded[0]),
            "funded-budget keys",
        )
        check.is_false(funded[0]["goal_reached"], "goal not reached")
        check.is_false(funded[0]["is_fillup"], "not a fill-up")

    ####################################################################
    #
    def test_recurring_budget_refreshed_notification_context(
        self,
        make_account: Callable[..., BankAccount],
        make_budget: Callable[..., Budget],
        system_user: User,
    ) -> None:
        """
        GIVEN: a RECURRING budget with $80 in fillup (target=$80),
               recur fires Feb 1 (last_recurrence_on=Jan 31)
        WHEN:  fund_account runs
        THEN:  a RECURRING_BUDGET_REFRESHED notification is created with all
               expected context keys; FUNDING_COMPLETE is not created because
               the FUND event contributes $0 (fillup at target) and the recur
               transfer is internal (fillup -> recurring, not unallocated)
        """
        today = date(2026, 2, 1)
        account = make_account(posted_through=today)
        # Fill-up at $80 with an $80 target, so the fund event sees no gap.
        recurring = make_budget(
            account,
            **_BILLS,
            fillup={
                "balance": Money(80, "USD"),
                "target_balance": Money(80, "USD"),
            },
            stored={
                "last_funded_on": today,
                "last_recurrence_on": date(2026, 1, 31),
            },
        )
        owner = account.owners.first()

        funding_svc.fund_account(account, today, system_user)

        n = Notification.objects.get(
            user=owner, kind=RECURRING_BUDGET_REFRESHED
        )
        check.equal(n.context["account_id"], str(account.id), "account id")
        check.equal(n.context["budget_id"], str(recurring.id), "budget id")
        check.is_true(
            {
                "account_name",
                "budget_name",
                "amount_received",
                "balance",
                "target_balance",
                "goal_reached",
                "date",
            }
            <= set(n.context),
            "context keys",
        )
        check.is_false(n.context["goal_reached"], "goal not reached")
        check.is_false(
            Notification.objects.filter(
                user=owner, kind=FUNDING_COMPLETE
            ).exists(),
            "no FUNDING_COMPLETE",
        )
