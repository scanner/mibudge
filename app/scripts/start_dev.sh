#!/bin/bash
#
# Start the mibudge development server.
#
# Runs migrations then starts runserver_plus (werkzeug) with hot-reload.
#

set -o errexit
set -o pipefail
set -o nounset

wait-for-it --service "${POSTGRES_HOST:-postgres}:${POSTGRES_PORT:-5432}" -- echo "PostgreSQL available"
wait-for-it --service "${REDIS_HOST:-redis}:${REDIS_PORT:-6379}" -- echo "Redis available"

python /app/manage.py migrate

exec python /app/manage.py runserver_plus 0.0.0.0:8000
