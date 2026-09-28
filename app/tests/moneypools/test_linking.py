"""Tests for opportunistic cross-account transaction linking."""

# system imports
#
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

# 3rd party imports
#
import pytest
import pytest_check as check
from djmoney.money import Money
from faker import Faker

# Project imports
#
from moneypools.models import BankAccount, Transaction
from moneypools.service.linking import attempt_link
from users.models import User

pytestmark = pytest.mark.django_db

# The driving transaction's date; counterparts are placed relative to it.
#
WHEN = datetime(2026, 3, 10, 12, tzinfo=UTC)


####################################################################
#
@pytest.fixture
def account_pair(
    user: User,
    bank_account_factory: Callable[..., BankAccount],
    faker: Faker,
) -> tuple[BankAccount, BankAccount]:
    """A (source, destination) pair of accounts owned by `user`.

    The source is a checking account; the destination is a credit card
    with a link alias.  Names, numbers and the alias are generated, so a
    test builds its description from the destination account -- its
    name, the last four digits of its number, or its alias -- to pick
    which matching rule links the pair.
    """
    src = bank_account_factory(
        name=faker.unique.company(),
        account_number=faker.bban(),
        owners=[user],
    )
    dst = bank_account_factory(
        name=faker.unique.company(),
        account_number=faker.credit_card_number(),
        link_aliases=[f"{faker.unique.company().upper()} CREDIT CRD"],
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
        "describe",
        [
            pytest.param(
                lambda dst, faker: (
                    f"ACH Transfer to {dst.name.upper()} PAYMENT -- ACH"
                ),
                id="name_substring",
            ),
            pytest.param(
                lambda dst, faker: (
                    "ACH DEPOSIT INTERNET TRANSFER FROM ACCOUNT ENDING IN "
                    f"{dst.account_number[-4:]}"
                ),
                id="last_4",
            ),
            # The alias is a vendor string that shares nothing with the
            # account's name, so only the alias can match it.
            pytest.param(
                lambda dst, faker: (
                    f"{dst.link_aliases[0]} DES:EPAY "
                    f"ID:{faker.numerify('XXXXX#####')} "
                    f"INDN:{faker.name().upper()} "
                    f"CO ID:{faker.numerify('XXXXX#####')} WEB"
                ),
                id="link_alias",
            ),
        ],
    )
    def test_happy_path(
        self,
        describe: Callable[[BankAccount, Faker], str],
        account_pair: tuple[BankAccount, BankAccount],
        transaction_factory: Callable[..., Transaction],
        faker: Faker,
    ) -> None:
        """
        GIVEN: two co-owned accounts and a counterpart transaction on
               the destination account
        WHEN:  a driving transaction is saved on the source with a
               description identifying the destination by name, by the
               last four digits of its number, or by a link alias
        THEN:  attempt_link pairs the two rows in both directions
        """
        src, dst = account_pair
        counterpart = transaction_factory(
            bank_account=dst,
            amount=100,
            posted_date=WHEN + timedelta(days=1),
            raw_description="counterpart",
        )
        driving = transaction_factory(
            bank_account=src,
            amount=-100,
            posted_date=WHEN,
            raw_description=describe(dst, faker),
        )

        linked = attempt_link(driving)

        assert linked is not None
        check.equal(linked.pkid, counterpart.pkid, "returns the counterpart")
        driving.refresh_from_db()
        counterpart.refresh_from_db()
        check.equal(
            driving.linked_transaction_id, counterpart.id, "driving -> other"
        )
        check.equal(
            counterpart.linked_transaction_id, driving.id, "other -> driving"
        )

    ####################################################################
    #
    @pytest.mark.parametrize(
        "counterparts",
        [
            # Outside the +/- 3 day window.
            pytest.param(
                [(Money("100.00", "USD"), timedelta(days=4))],
                id="out_of_window",
            ),
            # Magnitudes must be exactly equal.
            pytest.param(
                [(Money("100.01", "USD"), timedelta(0))],
                id="amount_off_by_a_cent",
            ),
            # An ambiguous match is worse than leaving the row orphaned
            # for the user to resolve.
            pytest.param(
                [
                    (Money("100.00", "USD"), timedelta(0)),
                    (Money("100.00", "USD"), timedelta(0)),
                ],
                id="ambiguous",
            ),
        ],
    )
    def test_no_link(
        self,
        counterparts: list[tuple[Money, timedelta]],
        account_pair: tuple[BankAccount, BankAccount],
        transaction_factory: Callable[..., Transaction],
    ) -> None:
        """
        GIVEN: candidates on the hinted account that are out of the
               date window, off by a cent, or more than one
        WHEN:  attempt_link runs
        THEN:  no link is established
        """
        src, dst = account_pair
        for amount, offset in counterparts:
            transaction_factory(
                bank_account=dst,
                amount=amount,
                posted_date=WHEN + offset,
                raw_description="counterpart",
            )
        driving = transaction_factory(
            bank_account=src,
            amount=Money("-100.00", "USD"),
            posted_date=WHEN,
            raw_description=f"Payment to {dst.name}",
        )

        check.is_none(attempt_link(driving), "returns None")
        driving.refresh_from_db()
        check.is_none(driving.linked_transaction_id, "nothing written")

    ####################################################################
    #
    def test_orphan_then_counterpart_links_both(
        self,
        account_pair: tuple[BankAccount, BankAccount],
        transaction_factory: Callable[..., Transaction],
    ) -> None:
        """
        GIVEN: the first side is imported before the counterpart exists
        WHEN:  the counterpart is later imported and attempt_link runs
        THEN:  both rows end up paired
        """
        src, dst = account_pair

        # First side imported alone -- nothing to link to yet.
        first = transaction_factory(
            bank_account=src,
            amount=-100,
            posted_date=WHEN,
            raw_description=f"Payment to {dst.name}",
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
            posted_date=WHEN,
            raw_description=f"Payment from {src.name}",
        )
        attempt_link(second)

        first.refresh_from_db()
        second.refresh_from_db()
        check.equal(first.linked_transaction_id, second.id, "first -> second")
        check.equal(second.linked_transaction_id, first.id, "second -> first")

    ####################################################################
    #
    def test_already_linked_is_noop(
        self,
        account_pair: tuple[BankAccount, BankAccount],
        transaction_factory: Callable[..., Transaction],
    ) -> None:
        """
        GIVEN: a transaction that is already linked
        WHEN:  attempt_link runs on it again
        THEN:  the existing counterpart is returned and nothing changes
        """
        src, dst = account_pair
        counterpart = transaction_factory(
            bank_account=dst,
            amount=100,
            posted_date=WHEN,
            raw_description="counterpart",
        )
        driving = transaction_factory(
            bank_account=src,
            amount=-100,
            posted_date=WHEN,
            raw_description=f"Payment to {dst.name}",
        )

        first = attempt_link(driving)
        assert first is not None
        assert first.pkid == counterpart.pkid

        # Second call must not re-link or alter state.
        driving.refresh_from_db()
        second = attempt_link(driving)
        assert second is not None
        assert second.pkid == counterpart.pkid
