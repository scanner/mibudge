"""
Redis-backed distributed locking.

Usage
-----
Any model that needs locking exposes a `lock_key` property.  Callers
acquire the lock via `acquire_lock`::

    with acquire_lock(budget.lock_key):
        with db_transaction.atomic():
            # safe to mutate state here
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
and before taking the matching row lock.  A thread that holds a row
lock and then waits for a Redis lock can deadlock against a thread
that holds the Redis lock and waits for the row.

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
