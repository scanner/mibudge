#!/bin/bash
#
# Start the Celery Flower monitoring dashboard.
#

set -o errexit
set -o pipefail
set -o nounset

wait-for-it --service "${REDIS_HOST:-redis}:${REDIS_PORT:-6379}" -- echo "Redis available"

exec celery flower \
    --app=config.celery_app \
    --broker="${CELERY_BROKER_URL}" \
    --basic_auth="${CELERY_FLOWER_USER}:${CELERY_FLOWER_PASSWORD}"
