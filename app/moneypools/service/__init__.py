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
- **Database write locks** (`_locking.locked` / `_locking.locked_many`)
  make every balance read-modify-write correct.  Each mutator re-reads
  the row it changes with `locked()` instead of `refresh_from_db()`,
  so the read happens under a lock held until the outermost
  transaction commits; a concurrent writer waits and then reads the
  committed value.  On Postgres the lock is a row lock
  (`SELECT ... FOR UPDATE`).  On SQLite it is the database write lock
  that `BEGIN IMMEDIATE` takes for the whole transaction
  (`common.db.apply_sqlite_locking`).

Correctness of balances rests on the database locks, not on Redis.
Every `locked()` call runs inside `db_transaction.atomic()`.

Lock order
----------
Both layers use the same order.  When a single operation needs more
than one lock, acquire in this order:

    bank_account -> transaction -> budget

Multiple budgets are locked sorted by `str(budget.id)`
(`locked_many` sorts for you).  Take each Redis lock before the
matching database lock.  On SQLite the database lock covers every row
at once, so the order matters only for the Redis locks.

`acquire_lock` is re-entrant per thread, so a service that locks every
budget it will touch up front (for example `transaction.split` or
`budget.archive`) can call other services that lock the same budgets.
See `common.locks` for details.
"""
