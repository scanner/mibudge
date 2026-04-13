"""Tests for opportunistic cross-account transaction linking."""

# system imports
#
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

# 3rd party imports
#
import pytest
from django.contrib.auth import get_user_model

# Project imports
#
from moneypools.linking import attempt_link
from moneypools.models import BankAccount, Transaction

# Direct factory imports needed here because @pytest.mark.parametrize
# arguments are evaluated before pytest fixtures are resolved.
#
from tests.users.factories import UserFactory

pytestmark = pytest.mark.django_db

User = get_user_model()


####################################################################
#
def _make_pair(
    user,
    bank_account_factory: Callable[..., BankAccount],
    *,
    src_name: str = "Checking",
    src_number: str = "111122223333",
    src_aliases: list[str] | None = None,
    dst_name: str = "Credit Card",
    dst_number: str = "444455556789",
    dst_aliases: list[str] | None = None,
) -> tuple[BankAccount, BankAccount]:
    """Build two bank accounts co-owned by ``user``."""
    src = bank_account_factory(
        name=src_name,
        account_number=src_number,
        link_aliases=src_aliases or [],
        owners=[user],
    )
    dst = bank_account_factory(
        name=dst_name,
        account_number=dst_number,
        link_aliases=dst_aliases or [],
        owners=[user],
    )
    return src, dst


########################################################################
########################################################################
#
class TestAttemptLink:
    """Direct tests of the pure matching logic."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "src_name,src_aliases,dst_name,dst_aliases,description",
        [
            # Name substring match (checking -> apple card by name).
            (
                "BofA Checking",
                [],
                "AppleCard",
                [],
                "ACH Transfer to APPLECARD GSBANK PAYMENT -- ACH",
            ),
            # Last-4 match via "ENDING IN NNNN".
            (
                "Apple Savings",
                [],
                "Scanner Savings",
                [],
                "ACH DEPOSIT INTERNET TRANSFER FROM ACCOUNT ENDING IN 5540",
            ),
            # Another last-4 match, different account number.
            (
                "Apple Card",
                [],
                "Scanner Savings",
                [],
                "ACH DEPOSIT INTERNET TRANSFER FROM ACCOUNT ENDING IN 2031",
            ),
            # link_aliases match when raw description uses an
            # unrelated vendor string ('CHASE CREDIT CRD').
            (
                "BofA Checking",
                [],
                "Chase Visa",
                ["CHASE CREDIT CRD"],
                "CHASE CREDIT CRD DES:EPAY ID:XXXXX26700 INDN:ERIC LUCE "
                "CO ID:XXXXX39224 WEB",
            ),
        ],
    )
    def test_happy_path(
        self,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
        src_name: str,
        src_aliases: list[str],
        dst_name: str,
        dst_aliases: list[str],
        description: str,
    ) -> None:
        """
        GIVEN: two co-owned accounts and a counterpart transaction on
               the destination account
        WHEN:  a driving transaction is saved on the source with a
               description identifying the destination
        THEN:  attempt_link pairs the two rows in both directions
        """
        user = UserFactory()
        # Use distinct account_number suffixes so the "ENDING IN NNNN"
        # tests match the *destination* account specifically.
        src_number = "000011112222"
        dst_number = (
            "999955405540"
            if "5540" in description
            else "999920312031"
            if "2031" in description
            else "888844445678"
        )
        src, dst = _make_pair(
            user,
            bank_account_factory,
            src_name=src_name,
            src_number=src_number,
            src_aliases=src_aliases,
            dst_name=dst_name,
            dst_number=dst_number,
            dst_aliases=dst_aliases,
        )

        when = datetime(2026, 3, 10, 12, tzinfo=UTC)
        counterpart = transaction_factory(
            bank_account=dst,
            amount=100,
            transaction_date=when + timedelta(days=1),
            raw_description="counterpart",
        )
        driving = transaction_factory(
            bank_account=src,
            amount=-100,
            transaction_date=when,
            raw_description=description,
        )

        linked = attempt_link(driving)

        assert linked is not None
        assert linked.pkid == counterpart.pkid
        driving.refresh_from_db()
        counterpart.refresh_from_db()
        assert driving.linked_transaction_id == counterpart.id
        assert counterpart.linked_transaction_id == driving.id

    ####################################################################
    #
    def test_out_of_window_no_link(
        self,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
    ) -> None:
        """
        GIVEN: a counterpart four days away from the driving tx
        WHEN:  attempt_link runs
        THEN:  no link is established (outside the +/- 3 day window)
        """
        user = UserFactory()
        src, dst = _make_pair(user, bank_account_factory)

        when = datetime(2026, 3, 10, 12, tzinfo=UTC)
        transaction_factory(
            bank_account=dst,
            amount=100,
            transaction_date=when + timedelta(days=4),
            raw_description="counterpart",
        )
        driving = transaction_factory(
            bank_account=src,
            amount=-100,
            transaction_date=when,
            raw_description="Payment to Credit Card",
        )

        assert attempt_link(driving) is None
        driving.refresh_from_db()
        assert driving.linked_transaction_id is None

    ####################################################################
    #
    def test_amount_mismatch_no_link(
        self,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
    ) -> None:
        """
        GIVEN: a candidate whose amount differs by 1 cent
        WHEN:  attempt_link runs
        THEN:  no link is established (magnitudes must be exactly equal)
        """
        user = UserFactory()
        src, dst = _make_pair(user, bank_account_factory)

        when = datetime(2026, 3, 10, 12, tzinfo=UTC)
        from djmoney.money import Money

        transaction_factory(
            bank_account=dst,
            amount=Money("100.01", "USD"),
            transaction_date=when,
            raw_description="counterpart",
        )
        driving = transaction_factory(
            bank_account=src,
            amount=Money("-100.00", "USD"),
            transaction_date=when,
            raw_description="Payment to Credit Card",
        )

        assert attempt_link(driving) is None

    ####################################################################
    #
    def test_ambiguous_candidates_no_link(
        self,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
    ) -> None:
        """
        GIVEN: two unlinked candidates on the same day with the same
               amount on the hinted account
        WHEN:  attempt_link runs
        THEN:  no link is written -- an ambiguous match is worse than
               leaving the row orphaned for the user to resolve
        """
        user = UserFactory()
        src, dst = _make_pair(user, bank_account_factory)

        when = datetime(2026, 3, 10, 12, tzinfo=UTC)
        transaction_factory(
            bank_account=dst,
            amount=100,
            transaction_date=when,
            raw_description="first",
        )
        transaction_factory(
            bank_account=dst,
            amount=100,
            transaction_date=when,
            raw_description="second",
        )
        driving = transaction_factory(
            bank_account=src,
            amount=-100,
            transaction_date=when,
            raw_description="Payment to Credit Card",
        )

        assert attempt_link(driving) is None
        driving.refresh_from_db()
        assert driving.linked_transaction_id is None

    ####################################################################
    #
    def test_orphan_then_counterpart_links_both(
        self,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
    ) -> None:
        """
        GIVEN: the first side is imported before the counterpart exists
        WHEN:  the counterpart is later imported and attempt_link runs
        THEN:  both rows end up paired
        """
        user = UserFactory()
        src, dst = _make_pair(user, bank_account_factory)

        when = datetime(2026, 3, 10, 12, tzinfo=UTC)

        # First side imported alone -- nothing to link to yet.
        first = transaction_factory(
            bank_account=src,
            amount=-100,
            transaction_date=when,
            raw_description="Payment to Credit Card",
        )
        first.refresh_from_db()
        assert first.linked_transaction_id is None

        # Counterpart arrives. Call attempt_link directly: the
        # signal -> Celery -> on_commit path is exercised via
        # transaction.on_commit which does not fire inside the
        # pytest-django test-wrapping transaction, so we drive the
        # pure logic here.
        second = transaction_factory(
            bank_account=dst,
            amount=100,
            transaction_date=when,
            raw_description="Payment from Checking",
        )
        attempt_link(second)

        first.refresh_from_db()
        second.refresh_from_db()
        assert first.linked_transaction_id == second.id
        assert second.linked_transaction_id == first.id

    ####################################################################
    #
    def test_already_linked_is_noop(
        self,
        bank_account_factory: Callable[..., BankAccount],
        transaction_factory: Callable[..., Transaction],
    ) -> None:
        """
        GIVEN: a transaction that is already linked
        WHEN:  attempt_link runs on it again
        THEN:  the existing counterpart is returned and nothing changes
        """
        user = UserFactory()
        src, dst = _make_pair(user, bank_account_factory)

        when = datetime(2026, 3, 10, 12, tzinfo=UTC)
        counterpart = transaction_factory(
            bank_account=dst,
            amount=100,
            transaction_date=when,
            raw_description="counterpart",
        )
        driving = transaction_factory(
            bank_account=src,
            amount=-100,
            transaction_date=when,
            raw_description="Payment to Credit Card",
        )

        first = attempt_link(driving)
        assert first is not None
        assert first.pkid == counterpart.pkid

        # Second call must not re-link or alter state.
        driving.refresh_from_db()
        second = attempt_link(driving)
        assert second is not None
        assert second.pkid == counterpart.pkid
