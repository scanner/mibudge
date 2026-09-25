"""
View helpers shared across the project's DRF APIs.

`AtomicWritesMixin` runs a view's writes in a transaction, the way
`ATOMIC_REQUESTS` does, and runs its reads outside one.
"""

# system imports
#
from collections.abc import Callable
from contextlib import ExitStack
from typing import Any

# 3rd party imports
#
from django.db import connections, transaction
from django.http import HttpRequest, HttpResponseBase
from rest_framework.permissions import SAFE_METHODS


########################################################################
########################################################################
#
def _atomic_request_aliases() -> list[str]:
    """Return the database aliases configured with `ATOMIC_REQUESTS`."""
    return [
        alias
        for alias, db in connections.settings.items()
        if db.get("ATOMIC_REQUESTS")
    ]


########################################################################
########################################################################
#
class AtomicWritesMixin:
    """Wrap unsafe methods in a transaction and run safe methods without one.

    `ATOMIC_REQUESTS` wraps every request in a transaction, reads
    included.  On SQLite a transaction opens with `BEGIN IMMEDIATE`
    (`common.db.apply_sqlite_locking`), which takes the database write
    lock, so every GET would wait for, and then block, every writer.
    This mixin excludes the view from `ATOMIC_REQUESTS` and opens the
    same transaction itself in `dispatch`, only for methods outside
    `SAFE_METHODS`.

    Writes keep `ATOMIC_REQUESTS` semantics: an exception rolls the
    transaction back, and so does an exception DRF turns into an error
    response (its `set_rollback` marks any open transaction on an alias
    with `ATOMIC_REQUESTS` for rollback).  Reads run in autocommit mode,
    each query on its own.

    Put it first among a viewset's bases.  A test in
    `app/tests/common/test_views.py` fails if a project API view that
    serves GET is left under `ATOMIC_REQUESTS`.
    """

    ####################################################################
    #
    @classmethod
    def as_view(cls, *args: Any, **kwargs: Any) -> Callable[..., Any]:
        """Return the view function, excluded from `ATOMIC_REQUESTS`."""
        view = super().as_view(*args, **kwargs)  # type: ignore[misc]
        for alias in _atomic_request_aliases():
            view = transaction.non_atomic_requests(using=alias)(view)
        return view

    ####################################################################
    #
    def dispatch(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> HttpResponseBase:
        """Dispatch the request, inside a transaction if it can write."""
        dispatch = super().dispatch  # type: ignore[misc]
        if request.method in SAFE_METHODS:
            return dispatch(request, *args, **kwargs)
        with ExitStack() as stack:
            for alias in _atomic_request_aliases():
                stack.enter_context(transaction.atomic(using=alias))
            return dispatch(request, *args, **kwargs)
