#!/usr/bin/env python
#
"""
Notification kind constants and registry for the moneypools app.

Call register_all() from MoneyPoolsConfig.ready() to make these kinds
available to the notification service.
"""

# system imports
#
from typing import Any

# 3rd party imports
#
from notifications.models import NotificationPriority
from notifications.registry import registry

# Dotted kind strings.  Import these in call sites rather than
# repeating the string literals.
#
FUNDING_COMPLETE = "moneypools.funding_complete"
IMPORT_COMPLETE = "moneypools.import_complete"
BUDGET_GOAL_REACHED = "moneypools.budget_goal_reached"
TRANSACTION_POSTED = "moneypools.transaction_posted"
BALANCE_MISMATCH = "moneypools.balance_mismatch"
IMPORT_ERROR = "moneypools.import_error"


########################################################################
########################################################################
#
def _account_owners(account: Any) -> Any:
    """Return the owners queryset for a BankAccount."""
    return account.owners.all()


########################################################################
########################################################################
#
def register_all() -> None:
    """Register all moneypools notification kinds with the registry.

    Called from MoneyPoolsConfig.ready().
    """
    registry.register(
        kind=FUNDING_COMPLETE,
        display_name="Funding cycle completed",
        default_priority=NotificationPriority.NORMAL,
        can_suppress=True,
        default_opt_in=True,
        recipients=_account_owners,
    )
    registry.register(
        kind=IMPORT_COMPLETE,
        display_name="Account import completed",
        default_priority=NotificationPriority.LOW,
        can_suppress=True,
        default_opt_in=False,
        recipients=_account_owners,
    )
    registry.register(
        kind=BUDGET_GOAL_REACHED,
        display_name="Budget goal reached",
        default_priority=NotificationPriority.NORMAL,
        can_suppress=True,
        default_opt_in=True,
        recipients=_account_owners,
    )
    registry.register(
        kind=TRANSACTION_POSTED,
        display_name="New transactions posted",
        default_priority=NotificationPriority.NORMAL,
        can_suppress=True,
        default_opt_in=True,
        recipients=_account_owners,
    )
    registry.register(
        kind=BALANCE_MISMATCH,
        display_name="Balance mismatch detected",
        default_priority=NotificationPriority.HIGH,
        can_suppress=False,
        default_opt_in=True,
        recipients=_account_owners,
    )
    registry.register(
        kind=IMPORT_ERROR,
        display_name="Import error",
        default_priority=NotificationPriority.HIGH,
        can_suppress=False,
        default_opt_in=True,
        recipients=_account_owners,
    )
