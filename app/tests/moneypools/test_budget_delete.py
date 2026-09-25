#!/usr/bin/env python
#
"""
Tests for `moneypools.service.budget.delete`: money held by the deleted
budget and its fill-up goal, and the ledger invariants checked by the
`verify_balances` command, after a delete.
"""

# system imports
#
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from io import StringIO

# 3rd party imports
#
import pytest
from django.core.management import call_command
from djmoney.money import Money

# Project imports
#
from moneypools.management.commands.verify_balances import (
    _check_budget_chain,
    _check_goal_invariant,
)
from moneypools.models import BankAccount, Budget, InternalTransaction
from moneypools.service import budget as budget_svc
from moneypools.service import internal_transaction as internal_transaction_svc
from moneypools.service import transaction as transaction_svc
from users.models import User

pytestmark = pytest.mark.django_db


########################################################################
########################################################################
#
def _at(day: int, hour: int = 0) -> datetime:
    """Return a UTC datetime on the given day of March 2026."""
    return datetime(2026, 3, day, hour, tzinfo=UTC)


########################################################################
########################################################################
#
def _assert_ledger_valid(account: BankAccount) -> None:
    """Assert every `verify_balances` invariant holds for `account`."""
    out = StringIO()
    call_command("verify_balances", account=str(account.id), stdout=out)


####################################################################
#
@pytest.fixture
def account(bank_account_factory: Callable[..., BankAccount]) -> BankAccount:
    """A bank account with $100 in Unallocated."""
    return bank_account_factory(
        available_balance=Money(100, "USD"),
        posted_balance=Money(100, "USD"),
    )


####################################################################
#
@pytest.fixture
def unallocated(account: BankAccount) -> Budget:
    """The Unallocated budget of `account`."""
    budget = account.unallocated_budget
    assert budget is not None
    return budget


####################################################################
#
@pytest.fixture
def make_goal(
    account: BankAccount, budget_factory: Callable[..., Budget]
) -> Callable[[str], Budget]:
    """Return a factory for zero-balance Goal budgets on `account`."""

    def _make(name: str) -> Budget:
        return budget_factory(
            bank_account=account,
            name=name,
            balance=Money(0, "USD"),
            budget_type=Budget.BudgetType.GOAL,
            funding_type=Budget.FundingType.FIXED_AMOUNT,
            funding_amount=Money(10, "USD"),
            target_balance=Money(100, "USD"),
        )

    return _make


####################################################################
#
@pytest.fixture
def recurring(
    account: BankAccount, budget_factory: Callable[..., Budget]
) -> Budget:
    """A zero-balance Recurring budget (with its fill-up) on `account`."""
    budget = budget_factory(
        bank_account=account,
        name="Groceries",
        balance=Money(0, "USD"),
        budget_type=Budget.BudgetType.RECURRING,
    )
    assert budget.fillup_goal is not None
    return budget


####################################################################
#
@pytest.fixture
def make_transfer(
    account: BankAccount, user: User
) -> Callable[[Budget, Budget, int, datetime], InternalTransaction]:
    """Return a factory for transfers between budgets on `account`."""

    def _make(
        src: Budget, dst: Budget, amount: int, when: datetime
    ) -> InternalTransaction:
        return internal_transaction_svc.create(
            bank_account=account,
            src_budget=src,
            dst_budget=dst,
            amount=Money(amount, "USD"),
            actor=user,
            effective_date=when,
        )

    return _make


####################################################################
#
@pytest.fixture
def make_purchase(
    account: BankAccount,
) -> Callable[[int, datetime, Budget | None], None]:
    """Return a factory for posted debits, optionally split to a budget."""

    def _make(amount: int, when: datetime, budget: Budget | None) -> None:
        tx = transaction_svc.create(
            bank_account=account,
            amount=Money(-amount, "USD"),
            posted_date=when,
            raw_description="PURCHASE",
        )
        if budget is not None:
            transaction_svc.split(tx, {str(budget.id): Decimal(amount)})

    return _make


########################################################################
########################################################################
#
class TestDeleteBudgetWithFillup:
    """Deleting a Recurring budget also clears its fill-up goal."""

    ####################################################################
    #
    def test_parent_and_fillup_balances_return_to_unallocated(
        self,
        account: BankAccount,
        unallocated: Budget,
        recurring: Budget,
        user: User,
        make_transfer: Callable[..., InternalTransaction],
        make_purchase: Callable[..., None],
    ) -> None:
        """
        GIVEN: a Recurring budget holding $40 and its fill-up holding
               $15, both funded from Unallocated, with purchases on
               Unallocated before and after the funding
        WHEN:  the Recurring budget is deleted
        THEN:  $55 returns to Unallocated
        AND:   the fill-up goal is deleted
        AND:   every verify_balances invariant holds
        """
        fillup = recurring.fillup_goal
        assert fillup is not None
        make_purchase(5, _at(1), None)
        make_transfer(unallocated, recurring, 40, _at(2, 12))
        make_transfer(unallocated, fillup, 15, _at(3, 12))
        make_purchase(5, _at(4), None)
        unallocated.refresh_from_db()
        before = unallocated.balance

        budget_svc.delete(recurring, actor=user)

        unallocated.refresh_from_db()
        assert unallocated.balance == before + Money(55, "USD")
        assert not Budget.objects.filter(id=fillup.id).exists()
        _assert_ledger_valid(account)

    ####################################################################
    #
    def test_fillup_with_allocations_blocks_delete(
        self,
        account: BankAccount,
        unallocated: Budget,
        recurring: Budget,
        user: User,
        make_transfer: Callable[..., InternalTransaction],
        make_purchase: Callable[..., None],
    ) -> None:
        """
        GIVEN: a Recurring budget whose fill-up goal has a transaction
               allocation
        WHEN:  the Recurring budget is deleted
        THEN:  ValueError is raised
        AND:   neither budget is deleted and no balance changes
        """
        fillup = recurring.fillup_goal
        assert fillup is not None
        make_transfer(unallocated, fillup, 15, _at(2, 12))
        make_purchase(5, _at(3), fillup)
        unallocated.refresh_from_db()
        before = unallocated.balance

        with pytest.raises(ValueError, match="transaction allocations"):
            budget_svc.delete(recurring, actor=user)

        assert Budget.objects.filter(id=recurring.id).exists()
        assert Budget.objects.filter(id=fillup.id).exists()
        unallocated.refresh_from_db()
        assert unallocated.balance == before
        _assert_ledger_valid(account)

    ####################################################################
    #
    def test_remaining_balance_follows_sign_rules(
        self,
        unallocated: Budget,
        recurring: Budget,
        user: User,
    ) -> None:
        """
        GIVEN: a Recurring budget holding $40 and its fill-up owing $15,
               with no transfers behind either balance
        WHEN:  the Recurring budget is deleted
        THEN:  Unallocated gains the $40 and absorbs the $15 deficit
        AND:   Unallocated's running-balance chain is valid
        """
        fillup = recurring.fillup_goal
        assert fillup is not None
        Budget.objects.filter(pk=recurring.pk).update(balance=Decimal(40))
        Budget.objects.filter(pk=fillup.pk).update(balance=Decimal(-15))
        unallocated.refresh_from_db()
        before = unallocated.balance

        budget_svc.delete(recurring, actor=user)

        unallocated.refresh_from_db()
        assert unallocated.balance == before + Money(25, "USD")
        assert _check_budget_chain(unallocated, Decimal("0")) == []


########################################################################
########################################################################
#
class TestDeleteBudgetWithTransfers:
    """Other budgets stay consistent when a budget's transfers cascade."""

    ####################################################################
    #
    def test_third_budget_chain_valid_after_delete(
        self,
        account: BankAccount,
        unallocated: Budget,
        user: User,
        make_goal: Callable[[str], Budget],
        make_transfer: Callable[..., InternalTransaction],
        make_purchase: Callable[..., None],
    ) -> None:
        """
        GIVEN: a Groceries Goal funded $50 from Unallocated, with a $5
               purchase before and a $5 purchase after it transferred
               $10 to a Vacation Goal
        WHEN:  the Vacation Goal is deleted
        THEN:  the $10 transfer is reversed onto Groceries
        AND:   Groceries' running-balance chain and Goal invariant hold
        AND:   every verify_balances invariant holds
        """
        groceries = make_goal("Groceries")
        vacation = make_goal("Vacation")
        make_transfer(unallocated, groceries, 50, _at(1, 12))
        make_purchase(5, _at(2), groceries)
        make_transfer(groceries, vacation, 10, _at(3, 12))
        make_purchase(5, _at(4), groceries)

        budget_svc.delete(vacation, actor=user)

        groceries.refresh_from_db()
        assert groceries.balance == Money(40, "USD")
        assert _check_budget_chain(groceries, Decimal("0")) == []
        assert _check_goal_invariant(groceries, Decimal("0")) is None
        _assert_ledger_valid(account)
