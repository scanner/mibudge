"""
InternalTransaction service -- Phase 1.

Planned operations:
    create(bank_account, src_budget, dst_budget, amount, actor)
        Sorted lock_budget on src + dst inside one atomic().
        Snapshots src_budget_balance / dst_budget_balance on the row.
    delete(internal_transaction)
        Reverses balance changes under sorted budget locks.
"""
