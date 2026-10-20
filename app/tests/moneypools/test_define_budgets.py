#!/usr/bin/env python
#
"""Test the define_budgets management command's --as-of option."""

# system imports
#
from collections.abc import Callable
from io import StringIO
from pathlib import Path

# 3rd party imports
#
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from freezegun import freeze_time

# Project imports
#
from moneypools.models import BankAccount

pytestmark = pytest.mark.django_db


####################################################################
#
@pytest.fixture
def budgets_yaml(account: BankAccount, tmp_path: Path) -> Path:
    """A definition file with one goal funding on the 15th of each month."""
    path = tmp_path / "budgets.yaml"
    path.write_text(
        f'bank_account: "{account.id}"\n'
        "budgets:\n"
        "  - name: Vacation\n"
        "    type: goal\n"
        "    funding_type: fixed_amount\n"
        '    target_balance: "300.00"\n'
        '    funding_amount: "50.00"\n'
        '    funding_schedule: "RRULE:FREQ=MONTHLY;BYMONTHDAY=15"\n'
    )
    return path


####################################################################
#
@pytest.fixture
def define_budgets(budgets_yaml: Path) -> Callable[..., str]:
    """Run define_budgets on `budgets_yaml` with extra args; its output."""

    def _run(*args: str) -> str:
        out = StringIO()
        call_command("define_budgets", str(budgets_yaml), *args, stdout=out)
        return out.getvalue()

    return _run


########################################################################
########################################################################
#
@freeze_time("2026-10-19")
class TestAsOf:
    """`--as-of` defines the budgets as if an earlier date were today."""

    ####################################################################
    #
    def test_dry_run_previews_from_the_date(
        self, define_budgets: Callable[..., str]
    ) -> None:
        """
        GIVEN: a goal funding on the 15th
        WHEN:  a dry run is made as of 2026-08-01
        THEN:  the preview lists the funding days from that date
        """
        output = define_budgets("--dry-run", "--as-of", "2026-08-01")

        assert "2026-08-15, 2026-09-15, 2026-10-15" in output

    ####################################################################
    #
    def test_refuses_a_date_after_today(
        self, define_budgets: Callable[..., str]
    ) -> None:
        """
        GIVEN: a definition file
        WHEN:  define_budgets runs as of tomorrow
        THEN:  it refuses, as the simulated clock cannot pass today
        """
        with pytest.raises(CommandError, match="later than today"):
            define_budgets("--as-of", "2026-10-20")
