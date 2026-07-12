# system imports
#
from datetime import UTC, date, datetime
from typing import Any

# 3rd party imports
#
from django.db.models.signals import pre_save
from django.dispatch import receiver

# Project imports
#
from .models import BankAccount, Budget, Transaction
from .service.schedules import normalize_dtstart


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
        Recurring (R) -- set True when balance >= target; cleared by
            the recurrence task on cycle reset, not by balance changes.

        Goal (G) -- completion is driven by funded_amount in the ITX
            service, not here.

        Capped (C) / Unallocated / Fill-up -- left unchanged.

    Args:
        sender: The Budget model class.
        instance: The Budget instance about to be saved.
        **kwargs: Additional signal keyword arguments.
    """
    acct_currency = instance.bank_account.currency
    instance.balance_currency = acct_currency  # type: ignore[attr-defined]
    instance.target_balance_currency = acct_currency  # type: ignore[attr-defined]

    # Invariant: a funding schedule never leaves save() without a
    # DTSTART anchored on a real rule occurrence.  Enforced here (not
    # only in the budget service) so the admin and import paths cannot
    # write bare RRULEs whose fire days would depend on the query
    # window.  Re-anchoring policy on edits lives in budget_svc.update.
    sched = instance.funding_schedule
    if sched and sched.rrules and sched.dtstart is None:
        instance.funding_schedule = normalize_dtstart(sched, date.today())

    # Set archived_at the first time a budget is archived.
    if instance.archived and instance.archived_at is None:
        instance.archived_at = datetime.now(UTC)

    # Recurring budgets flip complete=True when balance hits target; the
    # recurrence task clears it on cycle reset.  Goal completion is driven
    # by funded_amount in the ITX service, not here.  Capped budgets never
    # use complete; the engine uses the balance/target gap directly.
    target = instance.target_balance.amount
    balance = instance.balance.amount

    if target > 0 and instance.budget_type == Budget.BudgetType.RECURRING:
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
