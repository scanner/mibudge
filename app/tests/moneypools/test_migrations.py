#!/usr/bin/env python
#
"""
Tests for data migrations.

Data migrations are exercised by invoking their RunPython callables
against the live app registry, with rows staged in the legacy shape via
queryset updates (which bypass the signals that would otherwise prevent
that shape from existing).
"""

# system imports
#
from collections.abc import Callable
from datetime import UTC, datetime
from importlib import import_module

# 3rd party imports
#
import pytest
import recurrence
from django.apps import apps as django_apps

# Project imports
#
from moneypools.models import Budget

pytestmark = pytest.mark.django_db

_migration_0036 = import_module(
    "moneypools.migrations.0036_anchor_funding_schedule_dtstart"
)

# Serialized schedule shapes as they exist in legacy rows.
_BARE_SEMI_MONTHLY = recurrence.Recurrence(
    rrules=[recurrence.Rule(recurrence.MONTHLY, bymonthday=[15, -1])],
)
_ANCHORED_SEMI_MONTHLY = recurrence.Recurrence(
    dtstart=datetime(2026, 1, 15, tzinfo=UTC),
    rrules=[recurrence.Rule(recurrence.MONTHLY, bymonthday=[15, -1])],
)
_EXPIRED_RULE = recurrence.Recurrence(
    rrules=[
        recurrence.Rule(recurrence.MONTHLY, until=datetime(2020, 1, 1))
    ],
)


########################################################################
########################################################################
#
class TestAnchorFundingScheduleDtstart:
    """Migration 0036: backfill DTSTART on bare funding schedules."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "schedule,expected_dtstart",
        [
            # Bare rule: anchored at the first real occurrence on/after
            # the budget's creation date (May 19 -> May 31 on a 15th/EOM
            # rule -- not May 19 itself, which the rule never fires on).
            pytest.param(
                _BARE_SEMI_MONTHLY,
                datetime(2026, 5, 31, tzinfo=UTC),
                id="bare_rule_anchored",
            ),
            # Already anchored: left exactly as stored.
            pytest.param(
                _ANCHORED_SEMI_MONTHLY,
                datetime(2026, 1, 15, tzinfo=UTC),
                id="existing_anchor_preserved",
            ),
            # Rule with no occurrence on/after creation: left bare
            # rather than anchored on a day the rule never fires.
            pytest.param(_EXPIRED_RULE, None, id="expired_rule_skipped"),
        ],
    )
    def test_backfills_dtstart_from_creation_date(
        self,
        schedule: recurrence.Recurrence,
        expected_dtstart: datetime | None,
        budget_factory: Callable[..., Budget],
    ) -> None:
        """
        GIVEN: a budget row whose funding schedule is in a legacy shape
               (written via queryset update, bypassing the anchoring
               signal), created 2026-05-19
        WHEN:  migration 0036's RunPython callable runs
        THEN:  bare rules gain a DTSTART on their first real occurrence
               from the creation date; anchored and unanchorable rows
               are left untouched
        """
        budget = budget_factory()
        Budget.objects.filter(pkid=budget.pkid).update(
            funding_schedule=schedule,
            created_at=datetime(2026, 5, 19, tzinfo=UTC),
        )

        _migration_0036.anchor_funding_schedules(django_apps, None)

        budget.refresh_from_db()
        assert budget.funding_schedule.dtstart == expected_dtstart
