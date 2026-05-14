# system imports
#
from datetime import UTC, datetime
from typing import Any

# 3rd party imports
#
from django.db.models.signals import pre_save
from django.dispatch import receiver

# Project imports
#
from .models import BankAccount, Budget, Transaction


####################################################################
#
@receiver(pre_save, sender=BankAccount)
def bank_account_pre_save(
    sender: type[BankAccount], instance: BankAccount, **kwargs: Any
) -> None:
    """Propagate currency settings when a bank account is created.

    On creation, if no currency is set, inherits the bank's
    default_currency.  Always aligns posted_balance and
    available_balance currencies with the account's currency.

    Args:
        sender: The BankAccount model class.
        instance: The BankAccount instance about to be saved.
        **kwargs: Additional signal keyword arguments.
    """
    bank_account = instance

    if bank_account.pkid is None:
        # Default to the bank's currency if the caller did not
        # specify one.
        #
        if not bank_account.currency:
            bank_account.currency = bank_account.bank.default_currency

        # Align balance currencies with the account currency.
        #
        bank_account.posted_balance_currency = bank_account.currency
        bank_account.available_balance_currency = bank_account.currency


####################################################################
#
@receiver(pre_save, sender=Budget)
def budget_pre_save(
    sender: type[Budget], instance: Budget, **kwargs: Any
) -> None:
    """Align currencies and manage the 'complete' flag before each save.

    Currency alignment:
        Sets balance_currency and target_balance_currency to match the
        bank account's currency on every save so balances stay aligned
        if a budget is saved after its bank account's currency was
        corrected.

    'complete' flag management:
        Goal (G) -- set True when balance >= target; never cleared here.
            Once a goal is funded it stays funded regardless of spending.

        Capped (C) -- set True when balance >= target; cleared when
            balance drops below target.  This produces the "perpetual
            top-up to a cap" behavior: spending from the budget
            automatically re-enables automatic funding.

        Recurring (R) -- 'complete' is set True when balance >= target
            here, but it is cleared by the recurrence task (cycle reset),
            not by balance changes.

        Unallocated / Associated fill-up (no target) -- left unchanged.

    Args:
        sender: The Budget model class.
        instance: The Budget instance about to be saved.
        **kwargs: Additional signal keyword arguments.
    """
    acct_currency = instance.bank_account.currency
    instance.balance_currency = acct_currency  # type: ignore[attr-defined]
    instance.target_balance_currency = acct_currency  # type: ignore[attr-defined]

    # Set archived_at the first time a budget is archived.
    if instance.archived and instance.archived_at is None:
        instance.archived_at = datetime.now(UTC)

    # Manage 'complete' for Goal and Recurring budgets only.
    # target_balance of 0 means "no target set" -- skip those.
    # Capped budgets never set complete; the funding engine uses the
    # balance/target gap directly.
    #
    target = instance.target_balance.amount
    balance = instance.balance.amount

    if target > 0:
        match instance.budget_type:
            case Budget.BudgetType.GOAL | Budget.BudgetType.RECURRING:
                # Set when funded; never cleared here.
                # Goal: permanently done once funded.
                # Recurring: cleared by the recurrence task on cycle reset.
                if balance >= target:
                    instance.complete = True


####################################################################
#
@receiver(pre_save, sender=Transaction)
def transaction_pre_save(
    sender: type[Transaction], instance: Transaction, **kwargs: Any
) -> None:
    """Default the editable description from raw_description on first save.

    Bank-balance math is handled by TransactionService (Phase 4).

    Args:
        sender: The Transaction model class.
        instance: The Transaction instance about to be saved.
        **kwargs: Additional signal keyword arguments.
    """
    if not instance.description:
        instance.description = instance.raw_description.strip()
