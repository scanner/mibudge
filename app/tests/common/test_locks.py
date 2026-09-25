#!/usr/bin/env python
#
"""Tests for common.locks.acquire_lock."""

import logging
import threading
import time
from contextlib import ExitStack

# 3rd party imports
#
import pytest

# Project imports
#
from common import locks
from common.locks import acquire_lock
from common.redis import redis_client

# Upper bound for every wait, so a regression fails the test instead of
# hanging the run.
#
_TIMEOUT = 10.0


########################################################################
########################################################################
#
def _renewer_threads(key: str) -> list[threading.Thread]:
    """Return the live renewal threads for `key`."""
    return [t for t in threading.enumerate() if t.name == f"lock-renewer:{key}"]


####################################################################
#
@pytest.fixture
def short_ttl(monkeypatch: pytest.MonkeyPatch) -> float:
    """Shrink the lock TTL to 0.6s and the renewal interval to 0.1s.

    Returns:
        The shortened TTL in seconds.
    """
    monkeypatch.setattr(locks, "_LOCK_TIMEOUT", 0.6)
    monkeypatch.setattr(locks, "_RENEW_INTERVAL", 0.1)
    return 0.6


########################################################################
########################################################################
#
class TestAcquireLock:
    """Tests for the acquire_lock context manager."""

    ####################################################################
    #
    def test_key_exists_while_held_and_gone_after(
        self, use_fakeredis: object
    ) -> None:
        """
        GIVEN: a Redis key string
        WHEN:  acquire_lock is used as a context manager
        THEN:  the key exists in Redis inside the block and is gone after
        """
        key = "test:lock:acquire_lock"
        r = redis_client()

        assert r.exists(key) == 0
        with acquire_lock(key):
            assert r.exists(key) == 1
        assert r.exists(key) == 0

    ####################################################################
    #
    def test_lock_released_on_exception(self, use_fakeredis: object) -> None:
        """
        GIVEN: a Redis key string
        WHEN:  an exception is raised inside acquire_lock
        THEN:  the lock is released and the exception propagates
        """
        key = "test:lock:exception"
        r = redis_client()

        with pytest.raises(RuntimeError, match="boom"):
            with acquire_lock(key):
                raise RuntimeError("boom")

        assert r.exists(key) == 0

    ####################################################################
    #
    def test_multiple_locks_via_exitstack(self, use_fakeredis: object) -> None:
        """
        GIVEN: two distinct keys
        WHEN:  both are acquired via ExitStack
        THEN:  both keys exist while inside and are gone after exit
        """

        keys = ["test:lock:a", "test:lock:b"]
        r = redis_client()

        with ExitStack() as stack:
            for k in keys:
                stack.enter_context(acquire_lock(k))
            for k in keys:
                assert r.exists(k) == 1

        for k in keys:
            assert r.exists(k) == 0

    ####################################################################
    #
    def test_reentrant_within_one_thread(self, use_fakeredis: object) -> None:
        """
        GIVEN: a thread that holds a lock
        WHEN:  the same thread acquires the same key again
        THEN:  the nested acquire succeeds immediately, and the lock
               stays held until the outermost block exits
        """
        key = "test:lock:reentrant"
        r = redis_client()

        with acquire_lock(key) as outer:
            with acquire_lock(key, blocking=False) as inner:
                assert outer is True
                assert inner is True
            assert r.exists(key) == 1
        assert r.exists(key) == 0

    ####################################################################
    #
    def test_other_threads_still_excluded(self, use_fakeredis: object) -> None:
        """
        GIVEN: a thread that holds a lock
        WHEN:  another thread tries a non-blocking acquire of that key
        THEN:  the other thread does not get it
        """
        key = "test:lock:other-thread"
        results: list[bool] = []

        def _try() -> None:
            with acquire_lock(key, blocking=False) as got:
                results.append(got)

        with acquire_lock(key):
            t = threading.Thread(target=_try)
            t.start()
            t.join(timeout=5)

        assert results == [False]


########################################################################
########################################################################
#
class TestLockRenewal:
    """TTL renewal of held locks."""

    ####################################################################
    #
    def test_lock_outlives_its_ttl_while_held(
        self, use_fakeredis: object, short_ttl: float
    ) -> None:
        """
        GIVEN: a lock with a 0.6 second TTL
        WHEN:  the block holding it runs for three times the TTL
        THEN:  the lock is still held at the end of the block
        AND:   it is released when the block exits
        """
        key = "test:lock:renewed"
        r = redis_client()

        with acquire_lock(key):
            # Real time has to pass for the TTL to lapse; fakeredis
            # expires keys against the wall clock.
            #
            time.sleep(short_ttl * 3)
            assert r.exists(key) == 1
            assert int(r.pttl(key)) > 0  # type: ignore[arg-type]
        assert r.exists(key) == 0

    ####################################################################
    #
    def test_renewal_thread_stops_when_block_exits(
        self, use_fakeredis: object
    ) -> None:
        """
        GIVEN: a lock acquired and held by a nested acquire of the same
               key
        WHEN:  the blocks run and then exit
        THEN:  exactly one renewal thread runs while the lock is held
        AND:   no renewal thread remains after the outer block exits
        """
        key = "test:lock:one-renewer"

        with acquire_lock(key):
            with acquire_lock(key):
                assert len(_renewer_threads(key)) == 1
        assert _renewer_threads(key) == []

    ####################################################################
    #
    def test_failed_acquire_starts_no_renewal(
        self, use_fakeredis: object
    ) -> None:
        """
        GIVEN: a lock held by another thread
        WHEN:  this thread tries a non-blocking acquire and fails
        THEN:  no renewal thread is started for the failed attempt
        """
        key = "test:lock:no-renewer"
        results: list[tuple[bool, int]] = []

        def _try() -> None:
            with acquire_lock(key, blocking=False) as got:
                results.append((got, len(_renewer_threads(key))))

        with acquire_lock(key):
            t = threading.Thread(target=_try)
            t.start()
            t.join(timeout=_TIMEOUT)

        # One renewer: the holder's, not a second one for the failure.
        assert results == [(False, 1)]

    ####################################################################
    #
    def test_lost_lock_is_logged_not_raised(
        self,
        use_fakeredis: object,
        short_ttl: float,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """
        GIVEN: a held lock whose key disappears from Redis (it expired
               while the process stalled)
        WHEN:  the renewal runs and the block then exits
        THEN:  the loss is logged as an error
        AND:   exiting the block does not raise
        """
        key = "test:lock:lost"
        r = redis_client()

        with caplog.at_level(logging.ERROR, logger="common.locks"):
            with acquire_lock(key):
                r.delete(key)
                deadline = time.monotonic() + _TIMEOUT
                while not any(
                    "expired before it could be renewed" in m
                    for m in caplog.messages
                ):
                    assert time.monotonic() < deadline, "loss not logged"
                    time.sleep(0.01)

        assert any("no longer held when released" in m for m in caplog.messages)
