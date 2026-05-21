#!/bin/bash
#
# Start the gunicorn ASGI server on a Unix socket.
# Called by supervisord in the production container.
#

set -o errexit
set -o pipefail
set -o nounset

wait-for-it --service "${POSTGRES_HOST:-postgres}:${POSTGRES_PORT:-5432}" -- echo "Postgres available"
wait-for-it --service "${REDIS_HOST:-redis}:${REDIS_PORT:-6379}" -- echo "Redis available"

exec gunicorn config.asgi \
    --bind unix:/tmp/gunicorn.sock \
    --chdir /app \
    -k uvicorn.workers.UvicornWorker \
    --workers "${WEB_CONCURRENCY:-4}"
