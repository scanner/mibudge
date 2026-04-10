#!/bin/bash
#
# Start the mibudge web application (production).
#
# Starts gunicorn with uvicorn workers.
# Migrations are handled by the dedicated migrate container.
# Static files are collected at Docker build time.
#

set -o errexit
set -o pipefail
set -o nounset

wait-for-it --service "${REDIS_HOST:-redis}:${REDIS_PORT:-6379}" -- echo "Redis available"

exec gunicorn config.asgi \
    --bind 0.0.0.0:5000 \
    --chdir=/app \
    -k uvicorn.workers.UvicornWorker
