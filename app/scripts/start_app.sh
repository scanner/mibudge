#!/bin/bash
#
# Start the mibudge web application (production).
#
# Collects static files, runs migrations, then starts gunicorn with
# uvicorn workers.
#

set -o errexit
set -o pipefail
set -o nounset

wait-for-it --service "${POSTGRES_HOST:-postgres}:${POSTGRES_PORT:-5432}" -- echo "PostgreSQL available"
wait-for-it --service "${REDIS_HOST:-redis}:${REDIS_PORT:-6379}" -- echo "Redis available"

python /app/manage.py collectstatic --noinput
python /app/manage.py migrate

exec gunicorn config.asgi \
    --bind 0.0.0.0:5000 \
    --chdir=/app \
    -k uvicorn.workers.UvicornWorker
