"""
Row-lock helpers for balance read-modify-write in the service layer.

`locked` re-reads a model instance with `SELECT ... FOR UPDATE` and
refreshes it in place.  Postgres holds the row lock until the outermost
transaction commits, so a concurrent writer blocks at its own locked
read and then sees the committed value.  See `moneypools.service` for
the lock order and `common.locks` for how row locks relate to the Redis
locks.

`select_for_update()` raises `TransactionManagementError` outside a
transaction, so every call must run inside `db_transaction.atomic()`.
SQLite ignores `FOR UPDATE`; the Postgres test mode exercises the real
locking (see `CLAUDE.md`).

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
    """Re-read `obj` under a row lock and refresh it in place.

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
    """Return the sort key used to order row locks: `str(obj.id)`."""
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
        place under a row lock.
    """
    distinct: dict[object, M] = {}
    for obj in objs:
        distinct.setdefault(obj.pk, obj)
    ordered = sorted(distinct.values(), key=_id_key)
    for obj in ordered:
        locked(obj)
    return ordered
