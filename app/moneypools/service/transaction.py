"""
Transaction service -- Phase 4.

Planned operations:
    create(...)       -- lock_bank_account + atomic; saves tx, applies
                         bank-balance math, creates default allocation to
                         Unallocated, schedules linker via on_commit.
    update(tx, **changes)  -- mutable fields only (transaction_type, memo,
                              description).
    delete(tx)        -- lock_bank_account + per-budget locks, reverses
                         bank balance, deletes rows.
    split(tx, splits, actor)
                      -- full reconciliation: lock_transaction + atomic +
                         sorted budget locks via ExitStack; dispatches to
                         TransactionAllocationService primitives; enforces
                         sum == abs(tx.amount) with remainder to Unallocated.
"""
