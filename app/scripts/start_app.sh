#!/bin/bash
#
# Start the mibudge web application (production).
#
# Launches supervisord, which manages nginx (static files + reverse proxy on
# port 8000) and gunicorn (ASGI via Unix socket).
# Migrations are handled by the dedicated migrate container.
# Static files are collected at Docker build time.
#

set -o errexit
set -o pipefail
set -o nounset

exec /usr/bin/supervisord -c /etc/supervisor/supervisord.conf
