#!/usr/bin/env python
#
"""Tests for common.locks.acquire_lock."""

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
