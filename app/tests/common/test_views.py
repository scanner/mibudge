#!/usr/bin/env python
#
"""Tests for common.views.AtomicWritesMixin."""

# system imports
#
import threading
from collections.abc import Callable, Iterator
from typing import Any

# 3rd party imports
#
import pytest
from django.db import connection
from django.db import transaction as db_transaction
from django.urls import URLPattern, URLResolver, get_resolver, include, path
from rest_framework import status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.routers import SimpleRouter
from rest_framework.test import APIClient

# Project imports
#
from common.views import AtomicWritesMixin
from moneypools.models import Bank
from users.models import User

# Apps whose API views must follow the read/write transaction rule.
# Third-party views (drf-spectacular's schema views) are left alone.
#
_PROJECT_APPS = ("moneypools", "users", "notifications", "config", "common")

_SAFE = frozenset({"get", "head"})
_UNSAFE = frozenset({"post", "put", "patch", "delete"})

# Upper bound for every wait, so a regression fails the test instead of
# hanging the run.
#
_TIMEOUT = 15.0


########################################################################
########################################################################
#
class _ProbeViewSet(AtomicWritesMixin, viewsets.ViewSet):
    """Reports whether it ran in a transaction; `create` writes a Bank."""

    authentication_classes: list[Any] = []
    permission_classes = [AllowAny]

    def list(self, request: Request) -> Response:
        return Response({"in_atomic": connection.in_atomic_block})

    def create(self, request: Request) -> Response:
        Bank.objects.create(
            name=request.data["name"], routing_number="123456789"
        )
        fail = request.data.get("fail")
        if fail == "validation":
            raise ValidationError("rejected after writing")
        if fail == "crash":
            raise RuntimeError("crashed after writing")
        return Response(
            {"in_atomic": connection.in_atomic_block},
            status=status.HTTP_201_CREATED,
        )


_router = SimpleRouter()
_router.register("probe", _ProbeViewSet, basename="probe")

# URLconf for `@pytest.mark.urls(__name__)`.
urlpatterns = [path("", include(_router.urls))]


########################################################################
########################################################################
#
def _walk(
    patterns: list[URLPattern | URLResolver],
) -> Iterator[URLPattern]:
    """Yield every URLPattern in a (nested) URLconf."""
    for p in patterns:
        if isinstance(p, URLResolver):
            yield from _walk(p.url_patterns)
        else:
            yield p


########################################################################
########################################################################
#
def _methods(callback: Callable[..., Any]) -> set[str]:
    """Return the HTTP methods a DRF view callback handles."""
    actions = getattr(callback, "actions", None)
    if actions:
        methods = set(actions)
    else:
        cls = callback.cls  # type: ignore[attr-defined]
        methods = {m for m in cls.http_method_names if hasattr(cls, m)}
    if "get" in methods:
        methods.add("head")
    return methods


########################################################################
########################################################################
#
class TestProjectApiViews:
    """Every project API view follows the read/write transaction rule."""

    ####################################################################
    #
    def test_reads_run_outside_atomic_requests(self) -> None:
        """
        GIVEN: every DRF view in the project URLconf
        WHEN:  its transaction handling is inspected
        THEN:  a view that serves GET is excluded from ATOMIC_REQUESTS
        AND:   an excluded view that also accepts writes opens its own
               transaction for them through AtomicWritesMixin
        """
        failures = []
        for pattern in _walk(get_resolver().url_patterns):
            cb = pattern.callback
            cls = getattr(cb, "cls", None)
            if cls is None or not cls.__module__.startswith(_PROJECT_APPS):
                continue
            methods = _methods(cb)
            non_atomic = "default" in getattr(cb, "_non_atomic_requests", ())
            name = f"{cls.__module__}.{cls.__name__} ({pattern.pattern})"
            if methods & _SAFE and not non_atomic:
                failures.append(f"{name}: GET runs inside ATOMIC_REQUESTS")
            if (
                non_atomic
                and methods & _UNSAFE
                and not issubclass(cls, AtomicWritesMixin)
            ):
                failures.append(f"{name}: writes run without a transaction")
        assert failures == []


########################################################################
########################################################################
#
@pytest.mark.urls(__name__)
@pytest.mark.django_db(transaction=True, serialized_rollback=True)
class TestAtomicWritesMixin:
    """Transaction behaviour of views using AtomicWritesMixin.

    `transaction=True` runs each test outside the test-case transaction,
    so `connection.in_atomic_block` reflects the request alone.
    """

    ####################################################################
    #
    def test_get_runs_without_transaction(self, api_client: APIClient) -> None:
        """
        GIVEN: a view using AtomicWritesMixin
        WHEN:  it serves a GET
        THEN:  the handler runs with no transaction open
        """
        response = api_client.get("/probe/")

        assert response.status_code == status.HTTP_200_OK
        assert response.data == {"in_atomic": False}

    ####################################################################
    #
    def test_post_runs_in_transaction(self, api_client: APIClient) -> None:
        """
        GIVEN: a view using AtomicWritesMixin
        WHEN:  it serves a POST that writes a row
        THEN:  the handler runs inside a transaction
        AND:   the row is committed
        """
        response = api_client.post("/probe/", {"name": "Committed Bank"})

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data == {"in_atomic": True}
        assert Bank.objects.filter(name="Committed Bank").exists()

    ####################################################################
    #
    def test_error_response_rolls_back_write(
        self, api_client: APIClient
    ) -> None:
        """
        GIVEN: a view using AtomicWritesMixin
        WHEN:  a POST writes a row and then fails validation (400)
        THEN:  the row is rolled back
        """
        response = api_client.post(
            "/probe/", {"name": "Rejected Bank", "fail": "validation"}
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not Bank.objects.filter(name="Rejected Bank").exists()

    ####################################################################
    #
    def test_exception_rolls_back_write(self, api_client: APIClient) -> None:
        """
        GIVEN: a view using AtomicWritesMixin
        WHEN:  a POST writes a row and then raises an exception
        THEN:  the row is rolled back
        """
        with pytest.raises(RuntimeError, match="crashed after writing"):
            api_client.post(
                "/probe/", {"name": "Crashed Bank", "fail": "crash"}
            )

        assert not Bank.objects.filter(name="Crashed Bank").exists()


########################################################################
########################################################################
#
@pytest.mark.concurrency
@pytest.mark.django_db(transaction=True, serialized_rollback=True)
class TestReadsDuringWrites:
    """Reads are not held up by an open write transaction."""

    ####################################################################
    #
    def test_get_completes_while_a_writer_holds_its_transaction(
        self, user: User
    ) -> None:
        """
        GIVEN: a request that has written a row and not yet committed
        WHEN:  another client lists banks
        THEN:  the list returns without waiting for the writer
        """
        # Thread A writes inside an open transaction and holds it until
        # released.  On SQLite that transaction holds the database write
        # lock (`BEGIN IMMEDIATE`); a GET that opened its own
        # transaction would wait for it and then fail with "database is
        # locked".
        #
        written = threading.Event()
        release = threading.Event()
        errors: list[BaseException] = []

        def _writer() -> None:
            try:
                with db_transaction.atomic():
                    Bank.objects.create(
                        name="Uncommitted Bank", routing_number="987654321"
                    )
                    written.set()
                    if not release.wait(_TIMEOUT):
                        raise TimeoutError("writer was never released")
            except BaseException as exc:
                errors.append(exc)
            finally:
                written.set()
                connection.close()

        client = APIClient()
        client.force_authenticate(user=user)
        writer = threading.Thread(target=_writer, daemon=True)
        writer.start()
        try:
            assert written.wait(_TIMEOUT), "writer did not write"
            assert not errors, errors
            response = client.get("/api/v1/banks/")
        finally:
            release.set()
            writer.join(_TIMEOUT)

        assert response.status_code == status.HTTP_200_OK
        assert not writer.is_alive()
        assert not errors, errors
