"""
Shared utilities for the mibudge application.
"""

# system imports
#

# 3rd party imports
import redis
from django.conf import settings

########################################################################
#
# NOTE: All app code that needs a Redis client should call redis_client()
#       rather than constructing its own connection. This single pool is
#       monkeypatched in tests to point at a FakeServer so no real Redis
#       instance is required when running the test suite.
#
REDIS_CONNECTION_POOL = redis.ConnectionPool.from_url(settings.REDIS_URL)


####################################################################
#
def redis_client() -> redis.StrictRedis:
    """
    Return a Redis client backed by the shared connection pool.
    """
    return redis.StrictRedis(connection_pool=REDIS_CONNECTION_POOL)
