"""
TransactionAllocation service -- Phase 3.

Planned operations:
    create(transaction, budget, amount, category, memo)
    update_amount(allocation, new_amount)
    delete(allocation)

Each primitive wraps lock_budget around an atomic() that saves/mutates
budget.balance and walks the running-balance chain.

Helpers from signals.py that move here:
    _recalculate_running_balances(budget, from_transaction)
    _internal_transaction_delta(budget, after, before)
    _money_amount(value)

Convention: no view calls these primitives directly. All callers go through
TransactionService.split().
"""
