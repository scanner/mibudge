"""
Service layer for the moneypools domain.

Each module exposes module-level functions grouped by the entity they
primarily operate on.  The module is the service boundary; there are no
wrapper classes.

Locking convention
------------------
Use ``common.locks.acquire_lock`` with a model's ``lock_key`` property.
When a single operation needs more than one lock, acquire in this order:

    bank_account -> transaction -> budget

Multiple budget locks must be acquired sorted by ``budget.id`` to prevent
deadlocks.  Always hold the Redis lock across the enclosing
``db_transaction.atomic()`` -- see ``common.locks`` for details.
"""
