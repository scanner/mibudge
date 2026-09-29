"""
REST request bodies for the moneypools API tests.

Plain helpers, not fixtures, so `@pytest.mark.parametrize` can carry them.
Each builds a minimal valid create body; keyword arguments override or
add fields.
"""

# system imports
from typing import Any

# Project imports
from moneypools.models import BankAccount, Budget


####################################################################
#
def budget_payload(account: BankAccount, **fields: Any) -> dict:
    """A Goal budget create body for `account`."""
    return {
        "name": "Groceries",
        "bank_account": str(account.id),
        "budget_type": "G",
        "funding_type": "D",
        "target_balance": "100.00",
        **fields,
    }


####################################################################
#
def transaction_payload(account: BankAccount, **fields: Any) -> dict:
    """A posted purchase create body for `account`."""
    return {
        "bank_account": str(account.id),
        "amount": "-5.00",
        "posted_date": "2026-04-01T12:00:00Z",
        "transaction_type": "signature_purchase",
        "raw_description": "COFFEE SHOP",
        **fields,
    }


####################################################################
#
def transfer_payload(
    account: BankAccount, src: Budget, dst: Budget, **fields: Any
) -> dict:
    """An internal-transaction (transfer) create body from `src` to `dst`."""
    return {
        "bank_account": str(account.id),
        "amount": "10.00",
        "src_budget": str(src.id),
        "dst_budget": str(dst.id),
        **fields,
    }
