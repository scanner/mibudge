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

Lock TTL and renewal
--------------------
Each lock is created with a 30 second TTL, so a crashed process that
held one frees it within 30 seconds.  While a `with acquire_lock(...)`
block runs, a background thread resets the TTL every 10 seconds, so a
critical section that runs longer than the TTL (a large scrape sync,
a budget delete that recalculates many budgets) keeps its lock.  The
renewal thread stops when the block exits, and dies with the process
if it crashes.

If a renewal finds the lock no longer ours (the process stalled for
longer than the TTL and the key expired, possibly to be taken by
another holder), the loss is logged as an error and renewal stops.
Releasing a lost lock is logged too, instead of raising: balance
correctness rests on the database locks, and raising there would
discard work that is already correct.
"""

# system imports
#
import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager

# 3rd party imports
#
from redis.exceptions import LockNotOwnedError, RedisError
from redis.lock import Lock

# Project imports
#
from common.redis import redis_client

logger = logging.getLogger(__name__)

_LOCK_TIMEOUT = 30  # seconds

# How often a held lock's TTL is reset.  A third of the TTL leaves room
# for two missed renewals (a slow Redis round trip, a GC pause) before
# the key expires.
#
_RENEW_INTERVAL = _LOCK_TIMEOUT / 3  # seconds

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
class _Renewer:
    """Background thread that resets a held lock's TTL until stopped.

    Args:
        lock: The acquired lock.  It must be created with
            `thread_local=False` so this thread can see its token.
        key: The lock's key, for log messages.
    """

    ####################################################################
    #
    def __init__(self, lock: Lock, key: str) -> None:
        self._lock = lock
        self._key = key
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name=f"lock-renewer:{key}", daemon=True
        )
        self._thread.start()

    ####################################################################
    #
    def _run(self) -> None:
        """Reset the TTL every `_RENEW_INTERVAL` seconds until stopped."""
        while not self._stop.wait(_RENEW_INTERVAL):
            try:
                self._lock.reacquire()
            except LockNotOwnedError:
                logger.error(
                    "Redis lock %s expired before it could be renewed; "
                    "another holder may have taken it.",
                    self._key,
                )
                return
            except RedisError:
                # A failed round trip leaves the TTL where it was; the
                # next interval tries again before the key can expire.
                #
                logger.warning(
                    "Could not renew Redis lock %s; retrying.",
                    self._key,
                    exc_info=True,
                )

    ####################################################################
    #
    def stop(self) -> None:
        """Stop renewing and wait for the thread to exit."""
        self._stop.set()
        self._thread.join()


########################################################################
########################################################################
#
@contextmanager
def acquire_lock(key: str, blocking: bool = True) -> Iterator[bool]:
    """Acquire a named Redis lock for the duration of the block.

    Re-entrant per thread: when the current thread already holds `key`
    this yields True without touching Redis, and the outer block keeps
    ownership of the release.

    While the block runs, a background thread keeps resetting the lock's
    TTL (see "Lock TTL and renewal" above).

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

    # `thread_local=False` stores the lock token on the Lock object
    # rather than in thread-local storage, so the renewal thread can
    # reset the TTL.  Each Lock object belongs to this one `with` block.
    #
    lock = redis_client().lock(key, timeout=_LOCK_TIMEOUT, thread_local=False)
    acquired = lock.acquire(blocking=blocking)
    if not acquired:
        yield False
        return

    held.add(key)
    renewer = _Renewer(lock, key)
    try:
        yield True
    finally:
        held.discard(key)
        renewer.stop()
        try:
            lock.release()
        except LockNotOwnedError:
            logger.error(
                "Redis lock %s was no longer held when released; the "
                "block ran without its lock for part of the time.",
                key,
            )
