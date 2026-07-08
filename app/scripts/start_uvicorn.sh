#!/bin/bash
#
# Start the uvicorn ASGI server on a Unix socket.
# Called by supervisord in the production container.
#

set -o errexit
set -o pipefail
set -o nounset

wait-for-it --service "${POSTGRES_HOST:-postgres}:${POSTGRES_PORT:-5432}" -- echo "Postgres available"
wait-for-it --service "${REDIS_HOST:-redis}:${REDIS_PORT:-6379}" -- echo "Redis available"

cd /app

# NOTE: the socket is only reachable by the nginx inside this container, so
# its X-Forwarded-* headers are trusted unconditionally.
exec uvicorn config.asgi:application \
    --uds /tmp/uvicorn.sock \
    --workers "${WEB_CONCURRENCY:-4}" \
    --proxy-headers \
    --forwarded-allow-ips '*'
