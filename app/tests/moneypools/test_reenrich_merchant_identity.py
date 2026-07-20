#!/usr/bin/env python
#
"""Tests for the reenrich_merchant_identity management command."""

# system imports
#
from collections.abc import Callable
from io import StringIO

# 3rd party imports
#
import pytest
from django.core.management import call_command

# Project imports
#
from moneypools.models import BankAccount, Transaction, TransactionCategory
from users.models import User

pytestmark = pytest.mark.django_db


########################################################################
########################################################################
#
class TestReenrichMerchantIdentity:
    """Tests for the reenrich_merchant_identity management command."""

    ################################################################
    #
    @pytest.fixture
    def stale_tx(
        self,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
        transaction_category_factory: Callable[..., TransactionCategory],
        user: User,
    ) -> Transaction:
        """A transaction enriched before merchant-identity cleanup existed.

        Its details JSON is stored (so it counts as "already enriched"
        and is in scope for the command), but merchant_name still
        carries the raw, un-refined provider value -- the state every
        transaction enriched before this feature landed is in.
        """
        account = bank_account_factory(owners=[user])
        category = transaction_category_factory(
            group="Food & Drink", name="Snacks"
        )
        tx = transaction_factory(
            bank_account=account,
            pending=False,
            raw_description="TST*ACME BISTRO 07/09 MOBILE PURCHASE Palo Alto CA",
        )
        tx.details = {
            "merchant_name": "TST*ACME BISTRO",
            "merchant_category": "Eating Places and Restaurants",
        }
        tx.merchant_name = "TST*ACME BISTRO"
        tx.merchant_category = "Eating Places and Restaurants"
        tx.merchant_intermediary = None
        tx.description = "TST*ACME BISTRO (Eating Places and Restaurants)"
        # A user-assigned category must survive the re-enrich pass --
        # it is not something merchant-identity cleanup ever touches.
        tx.category = category
        tx.save()
        return tx

    ################################################################
    #
    def test_reenrich_recovers_store_and_intermediary(
        self, stale_tx: Transaction
    ) -> None:
        """
        GIVEN: an already-enriched transaction with a stale, un-refined
               merchant_name
        WHEN:  reenrich_merchant_identity runs
        THEN:  the store name and platform token are recovered, the
               description recomposes, and the user's category is
               untouched
        """
        original_category_id = stale_tx.category_id

        call_command("reenrich_merchant_identity", stdout=StringIO())

        stale_tx.refresh_from_db()
        assert stale_tx.merchant_name == "ACME BISTRO"
        assert stale_tx.merchant_intermediary == "toast"
        assert "via Toast" in stale_tx.description
        assert stale_tx.category_id == original_category_id

    ################################################################
    #
    def test_dry_run_makes_no_changes(self, stale_tx: Transaction) -> None:
        """
        GIVEN: a stale transaction
        WHEN:  reenrich_merchant_identity runs with --dry-run
        THEN:  the database is unchanged
        """
        call_command(
            "reenrich_merchant_identity", "--dry-run", stdout=StringIO()
        )

        stale_tx.refresh_from_db()
        assert stale_tx.merchant_name == "TST*ACME BISTRO"
        assert stale_tx.merchant_intermediary is None

    ################################################################
    #
    def test_account_filter_restricts_scope(
        self,
        stale_tx: Transaction,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
        user_factory: Callable[..., User],
    ) -> None:
        """
        GIVEN: stale transactions on two different accounts
        WHEN:  reenrich_merchant_identity runs with --account restricting
               to the other account
        THEN:  stale_tx (on the unselected account) is left untouched
        """
        other_account = bank_account_factory(owners=[user_factory()])
        transaction_factory(
            bank_account=other_account,
            pending=False,
            raw_description="SQ *OTHER SHOP 07/09 MOBILE PURCHASE CA",
        )

        call_command(
            "reenrich_merchant_identity",
            "--account",
            str(other_account.id),
            stdout=StringIO(),
        )

        stale_tx.refresh_from_db()
        assert stale_tx.merchant_name == "TST*ACME BISTRO"

    ################################################################
    #
    def test_rows_without_details_are_ignored(
        self,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
        user: User,
    ) -> None:
        """
        GIVEN: a posted transaction never enriched (details IS NULL)
        WHEN:  reenrich_merchant_identity runs
        THEN:  it is excluded from scope and the command reports zero
               transactions examined
        """
        account = bank_account_factory(owners=[user])
        transaction_factory(bank_account=account, pending=False)

        out = StringIO()
        call_command("reenrich_merchant_identity", stdout=out)

        assert "Re-enriching 0 transaction(s)" in out.getvalue()
