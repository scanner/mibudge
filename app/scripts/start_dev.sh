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

# docker-compose.yml sets DEV_TLS_CERT_FILE / DEV_TLS_KEY_FILE to this host's
# mkcert certificate under deployment/ssl/ (mounted at /mnt/ssl).  Serve TLS
# when this user can read both files; otherwise serve plain HTTP.
#
_CERT="${DEV_TLS_CERT_FILE:-}"
_KEY="${DEV_TLS_KEY_FILE:-}"

if [ -r "${_CERT}" ] && [ -r "${_KEY}" ]; then
    echo "Cert: ${_CERT}, key: ${_KEY}"
    echo "Starting runserver_plus with TLS.."
    exec python /app/manage.py runserver_plus \
        --cert-file "${_CERT}" --key-file "${_KEY}" 0.0.0.0:8000
fi

if [ -f "${_CERT}" ] && [ -f "${_KEY}" ]; then
    echo "TLS certificate exists but uid $(id -u) cannot read it:"
    ls -ln "${_CERT}" "${_KEY}"
else
    echo "No TLS certificate at '${_CERT}' -- run 'make certs' on this host."
fi
echo "Starting runserver_plus (without TLS).."
exec python /app/manage.py runserver_plus 0.0.0.0:8000
