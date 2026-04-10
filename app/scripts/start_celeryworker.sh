#!/bin/bash
#
# Start the Celery worker.
#

set -o errexit
set -o pipefail
set -o nounset

wait-for-it --service "${REDIS_HOST:-redis}:${REDIS_PORT:-6379}" -- echo "Redis available"

exec celery -A config.celery_app worker -l INFO
