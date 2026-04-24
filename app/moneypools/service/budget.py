"""
Budget service -- Phase 2.

Planned operations:
    create(...)   -- handles with_fillup_goal child creation
                     (moves out of budget_post_save signal).
    update(...)
    archive(budget, actor)  -- drains fill-up first, then this budget,
                               via InternalTransactionService.
    delete(budget, actor)   -- guards + drains remaining balance, then
                               cascade-deletes fill-up.
"""
