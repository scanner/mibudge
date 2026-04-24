"""
Redis-backed distributed locking.

Usage
-----
Any model that needs locking exposes a ``lock_key`` property.  Callers
acquire the lock via ``acquire_lock``::

    with acquire_lock(budget.lock_key):
        with db_transaction.atomic():
            # safe to mutate state here
            ...

Multiple locks (deadlock prevention)
-------------------------------------
Sort lock keys before acquiring.  Use ``contextlib.ExitStack`` when
locking more than one object at once::

    with ExitStack() as stack:
        for b in sorted(budgets, key=lambda b: b.id):
            stack.enter_context(acquire_lock(b.lock_key))
        with db_transaction.atomic():
            ...

Nesting rule
------------
Always acquire the Redis lock BEFORE opening ``db_transaction.atomic()``.
Never release the lock before the enclosing ``atomic()`` has committed.

Lock TTL
--------
30 seconds.  A safety net against crashed processes holding locks -- not a
substitute for fast critical sections.
"""

# system imports
#
from collections.abc import Iterator
from contextlib import contextmanager

# Project imports
#
from common.redis import redis_client

_LOCK_TIMEOUT = 30  # seconds


########################################################################
########################################################################
#
@contextmanager
def acquire_lock(key: str) -> Iterator[None]:
    """Acquire a named Redis lock for the duration of the block.

    Args:
        key: The Redis key to lock on.  Use a model's ``lock_key``
            property to produce a well-formed, collision-free key.

    Yields:
        None
    """
    with redis_client().lock(key, timeout=_LOCK_TIMEOUT):
        yield
