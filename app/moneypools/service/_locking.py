"""
Locked re-reads for balance read-modify-write in the service layer.

`locked` re-reads a model instance and refreshes it in place so that
the read happens under a database write lock that lasts until the
outermost transaction commits.  A concurrent writer to the same row
then waits and reads the committed value instead of overwriting it.
Each supported database provides that lock differently:

- **Postgres**: `SELECT ... FOR UPDATE` locks the row until the
  outermost commit.
- **SQLite**: `FOR UPDATE` is ignored.  The connection runs with
  `transaction_mode="IMMEDIATE"` (`common.db.apply_sqlite_locking`), so
  the enclosing `atomic()` already holds the database write lock from
  `BEGIN` to commit, and the re-read sees the committed row.

See `moneypools.service` for the lock order and `common.locks` for how
these database locks relate to the Redis locks.

Every call must run inside `db_transaction.atomic()`.  On Postgres,
`select_for_update()` raises `TransactionManagementError` outside a
transaction; on SQLite no lock would be held.  The race tests in
`app/tests/moneypools/test_concurrency.py` run on both databases.

Keep this module free of imports from other moneypools service modules
so any of them can import it.
"""

# system imports
#
from collections.abc import Iterable

# 3rd party imports
#
from django.db import models


########################################################################
########################################################################
#
def locked[M: models.Model](obj: M) -> M:
    """Re-read `obj` under a database write lock and refresh it in place.

    Args:
        obj: A saved model instance.  Its current field values are
            replaced by the committed row.

    Returns:
        The same instance, now holding the locked row's values.

    Raises:
        django.db.TransactionManagementError: If called outside
            `db_transaction.atomic()` on a backend that supports
            `SELECT ... FOR UPDATE`.
        django.core.exceptions.ObjectDoesNotExist: If the row has been
            deleted.
    """
    manager = type(obj)._default_manager
    obj.refresh_from_db(from_queryset=manager.select_for_update())
    return obj


########################################################################
########################################################################
#
def _id_key(obj: models.Model) -> str:
    """Return the sort key used to order database locks: `str(obj.id)`."""
    return str(obj.id)  # type: ignore[attr-defined]


########################################################################
########################################################################
#
def locked_many[M: models.Model](objs: Iterable[M]) -> list[M]:
    """Lock several rows of one model in `id` order.

    Duplicates (same `pk`) are locked once.  Locking in a fixed order
    keeps two callers that lock overlapping sets from deadlocking.

    Args:
        objs: Saved model instances that have an `id` field.

    Returns:
        The distinct instances, sorted by `str(id)`, each refreshed in
        place under a database lock.
    """
    distinct: dict[object, M] = {}
    for obj in objs:
        distinct.setdefault(obj.pk, obj)
    ordered = sorted(distinct.values(), key=_id_key)
    for obj in ordered:
        locked(obj)
    return ordered
