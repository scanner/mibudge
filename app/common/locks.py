"""
Redis-backed distributed locking.

Two-layer locking model
-----------------------
Balance-bearing rows (`BankAccount`, `Budget`, `Transaction`) are
protected by two layers that do different jobs:

1. **Redis locks (this module)** serialize work across processes before
   the database is touched, and give single-flight behaviour to jobs
   that should not run twice at once (the non-blocking funding lock).
   A Redis lock is released when its `with` block exits, which is often
   before the enclosing database transaction commits: an HTTP request
   runs inside `ATOMIC_REQUESTS`, and a service called by another
   service runs inside the caller's `atomic()`.

2. **Database write locks** make balance read-modify-write correct.
   `moneypools.service._locking.locked` re-reads each row it changes
   under a lock held until the *outermost* transaction commits or rolls
   back, so a second writer re-reads the committed value instead of
   overwriting it.  On Postgres that is a row lock
   (`SELECT ... FOR UPDATE`); on SQLite it is the database write lock
   taken by `BEGIN IMMEDIATE` (`common.db.apply_sqlite_locking`).

Correctness of balances rests on the database locks.  The Redis lock
narrows contention and orders work across processes; it does not have
to outlive the commit.

Usage
-----
Any model that needs locking exposes a `lock_key` property.  Callers
acquire the Redis lock, open `atomic()`, then re-read the rows they
mutate under a database lock::

    with acquire_lock(budget.lock_key):
        with db_transaction.atomic():
            locked(budget)
            # safe to mutate budget here
            ...

Multiple locks (deadlock prevention)
-------------------------------------
Sort lock keys before acquiring.  Use `contextlib.ExitStack` when
locking more than one object at once::

    with ExitStack() as stack:
        for b in sorted(budgets, key=lambda b: str(b.id)):
            stack.enter_context(acquire_lock(b.lock_key))
        with db_transaction.atomic():
            ...

Nesting rule
------------
Always acquire the Redis lock BEFORE opening `db_transaction.atomic()`
and before taking the matching database lock.  A thread that holds a
database lock and then waits for a Redis lock can deadlock against a
thread that holds the Redis lock and waits for the database.

Re-entrancy
-----------
`acquire_lock` is re-entrant per thread: a thread that already holds a
key gets it again immediately, and only the outermost `with` block
releases it.  This lets a service take the locks for every row it will
touch up front, in sorted order, and then call other services that
lock the same keys.

Lock TTL
--------
30 seconds.  A safety net against crashed processes holding locks -- not a
substitute for fast critical sections.
"""

# system imports
#
import threading
from collections.abc import Iterator
from contextlib import contextmanager

# Project imports
#
from common.redis import redis_client

_LOCK_TIMEOUT = 30  # seconds

# Keys held by the current thread.  Checked before asking Redis so a
# nested acquire of a key this thread already holds does not wait on
# itself.
#
_held = threading.local()


########################################################################
########################################################################
#
def _held_keys() -> set[str]:
    """Return the set of lock keys held by the current thread."""
    keys: set[str] | None = getattr(_held, "keys", None)
    if keys is None:
        keys = set()
        _held.keys = keys
    return keys


########################################################################
########################################################################
#
@contextmanager
def acquire_lock(key: str, blocking: bool = True) -> Iterator[bool]:
    """Acquire a named Redis lock for the duration of the block.

    Re-entrant per thread: when the current thread already holds `key`
    this yields True without touching Redis, and the outer block keeps
    ownership of the release.

    Args:
        key: The Redis key to lock on.  Use a model's `lock_key`
            property to produce a well-formed, collision-free key.
        blocking: When True (the default), wait until the lock is
            available.  When False, attempt to acquire once and yield
            False if another holder has it -- the caller is then
            expected to branch on the yielded value rather than
            mutating state.

    Yields:
        True if the lock was acquired (or is already held by this
        thread), False otherwise (only possible when `blocking=False`).
        Existing blocking call sites can ignore the value.
    """
    held = _held_keys()
    if key in held:
        yield True
        return

    lock = redis_client().lock(key, timeout=_LOCK_TIMEOUT)
    acquired = lock.acquire(blocking=blocking)
    if acquired:
        held.add(key)
    try:
        yield acquired
    finally:
        if acquired:
            held.discard(key)
            lock.release()
