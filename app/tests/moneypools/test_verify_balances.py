"""Tests for the verify_balances management command."""

# system imports
from collections.abc import Callable
from decimal import Decimal
from io import StringIO

# 3rd party imports
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from djmoney.money import Money

# Project imports
from moneypools.models import BankAccount

pytestmark = pytest.mark.django_db


########################################################################
####################################################################
#
class TestVerifyBalances:
    """Tests for verify_balances."""

    ####################################################################
    #
    def test_balanced_account_passes(
        self,
        bank_account_factory: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: a freshly created bank account with zero posted_balance
               and an auto-created zero-balance Unallocated budget
        WHEN:  verify_balances runs
        THEN:  the command succeeds with a PASS line for the account
        """
        bank_account_factory()
        out = StringIO()
        call_command("verify_balances", stdout=out)
        assert "PASS" in out.getvalue()
        assert "FAIL" not in out.getvalue()

    ####################################################################
    #
    def test_mismatch_raises_command_error(
        self,
        bank_account_factory: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: an account whose posted_balance does not equal the sum of
               its budget balances
        WHEN:  verify_balances runs
        THEN:  the command raises CommandError and reports the failing
               account with a per-budget breakdown
        """
        account = bank_account_factory()
        # Force an invariant break by pushing posted_balance away from
        # the sum of budget balances (which is zero for a fresh account).
        account.posted_balance = Money("100.00", account.currency)
        account.save()

        out = StringIO()
        with pytest.raises(CommandError):
            call_command("verify_balances", stdout=out)
        output = out.getvalue()
        assert "FAIL" in output
        assert "delta=100.00" in output
        # Per-budget breakdown should name the Unallocated budget.
        assert "Unallocated" in output

    ####################################################################
    #
    def test_tolerance_absorbs_small_delta(
        self,
        bank_account_factory: Callable[..., BankAccount],
    ) -> None:
        """
        GIVEN: an account that is off by a penny
        WHEN:  verify_balances runs with --tolerance 0.01
        THEN:  the account is reported as PASS
        """
        account = bank_account_factory()
        account.posted_balance = Money("0.01", account.currency)
        account.save()

        out = StringIO()
        call_command(
            "verify_balances", "--tolerance", Decimal("0.01"), stdout=out
        )
        assert "PASS" in out.getvalue()
