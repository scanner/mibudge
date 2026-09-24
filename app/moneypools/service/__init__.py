"""
Service layer for the moneypools domain.

Each module exposes module-level functions grouped by the entity they
primarily operate on.  The module is the service boundary; there are no
wrapper classes.

Locking model
-------------
Balance-bearing rows (`BankAccount`, `Budget`, and `Transaction` for
its `pending` state and snapshots) are protected by two layers:

- **Redis locks** (`common.locks.acquire_lock` with a model's
  `lock_key`) serialize work across processes before the database is
  touched and give single-flight behaviour, such as the non-blocking
  per-account lock in `funding.fund_account`.  A Redis lock is often
  released before the enclosing transaction commits: HTTP requests run
  inside `ATOMIC_REQUESTS`, and a service called by another service
  runs inside the caller's `atomic()`.
- **Row locks** (`_locking.locked` / `_locking.locked_many`, i.e.
  `SELECT ... FOR UPDATE`) make every balance read-modify-write
  correct.  Each mutator re-reads the row it changes under a row lock
  instead of `refresh_from_db()`.  Postgres holds the lock until the
  outermost transaction commits, so a concurrent writer waits and then
  reads the committed value.

Correctness of balances rests on the row locks.  Every
`locked()` call runs inside `db_transaction.atomic()`; outside one,
`select_for_update()` raises `TransactionManagementError`.

Lock order
----------
Both layers use the same order.  When a single operation needs more
than one lock, acquire in this order:

    bank_account -> transaction -> budget

Multiple budgets are locked sorted by `str(budget.id)`
(`locked_many` sorts for you).  Take each Redis lock before the
matching row lock.  `acquire_lock` is re-entrant per thread, so a
service that locks every budget it will touch up front (for example
`transaction.split` or `budget.archive`) can call other services that
lock the same budgets.  See `common.locks` for details.
"""
