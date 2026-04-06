#!/bin/bash
#
# Start the mibudge development server.
#
# Runs migrations then starts runserver_plus (werkzeug) with hot-reload.
#

set -o errexit
set -o pipefail
set -o nounset

wait-for-it --service "${REDIS_HOST:-redis}:${REDIS_PORT:-6379}" -- echo "Redis available"

# If SSL certs are mounted, start with TLS; otherwise start without.
#
_CERT="/mnt/ssl/ssl_crt.pem"
_KEY="/mnt/ssl/ssl_key.pem"

if [ -f "${_CERT}" ] && [ -f "${_KEY}" ]; then
    echo "Starting runserver_plus with TLS.."
    exec python /app/manage.py runserver_plus \
        --cert-file "${_CERT}" --key-file "${_KEY}" 0.0.0.0:8000
fi

echo "Starting runserver_plus.."
exec python /app/manage.py runserver_plus 0.0.0.0:8000
