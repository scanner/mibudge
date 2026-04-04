#!/bin/bash
#
# Start the Celery beat scheduler.
#

set -o errexit
set -o pipefail
set -o nounset

wait-for-it --service "${POSTGRES_HOST:-postgres}:${POSTGRES_PORT:-5432}" -- echo "PostgreSQL available"
wait-for-it --service "${REDIS_HOST:-redis}:${REDIS_PORT:-6379}" -- echo "Redis available"

rm -f './celerybeat.pid'
exec celery -A config.celery_app beat -l INFO
