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
# SSL_CERT_FILE / SSL_KEY_FILE come from .env (filenames within deployment/ssl/).
# Fall back to the unprefixed names for single-host setups or prod.
#
_SSL_DIR="/mnt/ssl"
_CERT="${_SSL_DIR}/${SSL_CERT_FILE:-ssl_crt.pem}"
_KEY="${_SSL_DIR}/${SSL_KEY_FILE:-ssl_key.pem}"

echo "Cert: ${_CERT}, key: ${_KEY}"

if [ -f "${_CERT}" ] && [ -f "${_KEY}" ]; then
    echo "Starting runserver_plus with TLS.."
    exec python /app/manage.py runserver_plus \
        --cert-file "${_CERT}" --key-file "${_KEY}" 0.0.0.0:8000
fi

echo "Starting runserver_plus (without TLS).."
exec python /app/manage.py runserver_plus 0.0.0.0:8000
