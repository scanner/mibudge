#!/usr/bin/env python
#
"""Tests for common.locks.acquire_lock."""

import threading
from contextlib import ExitStack

# 3rd party imports
#
import pytest

# Project imports
#
from common.locks import acquire_lock
from common.redis import redis_client


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
