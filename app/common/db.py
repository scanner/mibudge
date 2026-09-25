"""
Database settings shared by the Django settings module and the tests.

Keep this module free of Django model imports so `config.settings` can
import it.
"""

# system imports
#
from typing import Any

SQLITE_ENGINE = "django.db.backends.sqlite3"


########################################################################
########################################################################
#
def apply_sqlite_locking(db: dict[str, Any]) -> None:
    """Make SQLite transactions take the write lock when they begin.

    SQLite has no row locks and ignores `SELECT ... FOR UPDATE`.  With
    `transaction_mode="IMMEDIATE"` every `atomic()` block opens with
    `BEGIN IMMEDIATE`, which takes the database write lock at once and
    holds it until commit.  A second writer then waits at its own
    `BEGIN` (up to the connection timeout, 5 seconds by default) and
    reads the committed balance, which meets the same rule the row locks
    meet on Postgres (see `moneypools.service._locking`).  In SQLite's
    default deferred mode the second writer instead fails with
    `database is locked` when it tries to write.

    With `ATOMIC_REQUESTS` every request holds the write lock for its
    whole duration, so requests to one SQLite database run one at a
    time.

    Does nothing for other engines.

    Args:
        db: One entry of `settings.DATABASES`, modified in place.
    """
    if db.get("ENGINE") != SQLITE_ENGINE:
        return
    db.setdefault("OPTIONS", {})["transaction_mode"] = "IMMEDIATE"
