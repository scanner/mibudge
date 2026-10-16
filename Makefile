# -*- Mode: Makefile -*-
ROOT_DIR := $(shell git rev-parse --show-toplevel)
# This host's name: DEV_HOSTNAME from .env once it exists, so the
# certificate, compose and Vite agree even if `hostname` later changes.
DEV_HOSTNAME := $(or $(shell sed -n 's/^DEV_HOSTNAME=//p' $(ROOT_DIR)/.env 2>/dev/null),$(shell hostname))
SSL_DIR := $(ROOT_DIR)/deployment/ssl
include $(ROOT_DIR)/Make.rules

DOCKER_BUILDKIT := 1

.PHONY: check-env certs dirs dbs ssl clean purge test test-frontend logs migrate makemigrations createadmin manage_shell shell restart down up up-backend build env uv-sync uv-lock uv-add uv-add-dev uv-upgrade api-schema api-docs tag publish-tag help

env: $(ROOT_DIR)/.env	## Create this host's .env from deployment/dot-env.dev (never overwrites)

$(ROOT_DIR)/.env:
	@sed 's/@HOSTNAME@/$(DEV_HOSTNAME)/g' $(ROOT_DIR)/deployment/dot-env.dev > $@
	@echo "Created .env for $(DEV_HOSTNAME) from deployment/dot-env.dev"

# Refuse to start the stack with a .env from before deployment/dot-env.dev
# gained DEV_HOSTNAME.
check-env: $(ROOT_DIR)/.env
	@grep -q '^DEV_HOSTNAME=' $(ROOT_DIR)/.env || { \
	    echo ".env predates DEV_HOSTNAME. Regenerate it, then copy back any"; \
	    echo "settings of your own:  mv .env .env.old && make env"; \
	    exit 1; }
	@if [ -e $(ROOT_DIR)/deployment/local-dev-docker.env ]; then \
	    echo "NOTE: deployment/local-dev-docker.env is no longer used; delete it."; \
	fi

# mypy's Django plugin imports `config.settings`, which reads `.env`.
lint: $(ROOT_DIR)/.env

build: version	## Build prod and dev Docker images, tagged with the version
	@COMPOSE_DOCKER_CLI_BUILD=1 DOCKER_BUILDKIT=1 docker build --build-arg PYTHON_VERSION="$(PYTHON_VERSION)" --build-arg VERSION="$(VERSION)" --target prod --tag mibudge:$(VERSION) --tag mibudge:latest .
	@COMPOSE_DOCKER_CLI_BUILD=1 DOCKER_BUILDKIT=1 docker build --build-arg PYTHON_VERSION="$(PYTHON_VERSION)" --build-arg VERSION="$(VERSION)" --target dev --tag mibudge:$(VERSION)-dev --tag mibudge:dev .

dirs: dbs ssl     ## Make the local directories for dbs, ssl, etc.

dbs:
	@mkdir -p $(ROOT_DIR)/deployment/db_backups

ssl:
	@mkdir -p $(SSL_DIR)

CERT_FILE := $(SSL_DIR)/$(DEV_HOSTNAME)-ssl_crt.pem
KEY_FILE := $(SSL_DIR)/$(DEV_HOSTNAME)-ssl_key.pem
CERT_RENEW_DAYS := 30

# Create this host's certificate when it is missing, expires within
# CERT_RENEW_DAYS, or was not signed by this machine's mkcert CA (checked by
# signature: every mkcert CA a user creates on one host has the same name).
# The dev server reads the certificate at startup, so a running backend is
# restarted to load a new one.  File sync may not keep file modes, so every
# host's key in deployment/ssl/ is made readable by its owner only.
# NOTE: The dev container (uid 900) can read an owner-only key because Docker
#       Desktop on macOS presents bind-mounted files as owned by the container
#       user.  Native Docker on Linux keeps the host uid, so a Linux dev host
#       would need the dev containers to run as the host user.
certs: | ssl	## Create or renew this host's TLS certificate in deployment/ssl/ with mkcert
	@ca="$$(mkcert -CAROOT)/rootCA.pem"; \
	if [ ! -f "$$ca" ]; then \
	    echo "No mkcert CA at $$ca -- run 'mkcert -install' first."; exit 1; \
	fi; \
	reason=""; \
	if [ ! -f $(CERT_FILE) ] || [ ! -f $(KEY_FILE) ]; then \
	    reason="none exists"; \
	elif ! openssl x509 -noout -checkend $$(( $(CERT_RENEW_DAYS) * 86400 )) \
	        -in $(CERT_FILE) > /dev/null; then \
	    reason="it expires within $(CERT_RENEW_DAYS) days"; \
	elif ! openssl verify -CAfile "$$ca" $(CERT_FILE) > /dev/null 2>&1; then \
	    reason="this machine's mkcert CA did not sign it"; \
	fi; \
	if [ -n "$$reason" ]; then \
	    echo "Creating the TLS certificate for $(DEV_HOSTNAME): $$reason"; \
	    mkcert -key-file $(KEY_FILE) -cert-file $(CERT_FILE) \
	        $(DEV_HOSTNAME) localhost 127.0.0.1 ::1 || exit 1; \
	    if [ -n "$$(docker compose ps --quiet backend 2> /dev/null)" ]; then \
	        echo "Restarting backend to load the new certificate"; \
	        docker compose restart backend; \
	    fi; \
	fi; \
	chmod 600 $(SSL_DIR)/*-ssl_key.pem

up-backend: check-env build dirs certs	## Build the backend stack and bring it up detached (everything except the foreground Vite dev server)
	@docker compose up --remove-orphans --detach

up: up-backend	## Bring up the backend stack, then run Vite in the foreground
	@echo "Backend stack running in the background. Starting Vite dev server..."
	@echo "(Ctrl-C stops Vite; backend containers keep running -- use 'make down' to stop them.)"
	@cd $(ROOT_DIR)/frontend && pnpm dev || (echo "\nVite failed to start -- is the dev server already running on port 5173?" && exit 1)

down:	## docker compose down
	@docker compose down --remove-orphans

purge:	## docker compose down, removing all volumes (destroys db data)
	@docker compose down --remove-orphans --volumes

restart: down up	## docker compose down, then up

shell:	## Make a bash shell in an ephemeral backend container
	@docker compose run --rm backend /bin/bash

manage_shell:	## Run manage.py shell_plus in a backend container
	@docker compose run --rm backend python manage.py shell_plus

migrate:	## Run manage.py migrate
	@docker compose run --rm backend python manage.py migrate

makemigrations:	## Run manage.py makemigrations
	@PYTHONPATH=$(ROOT_DIR)/app $(UV_RUN) python app/manage.py makemigrations

createadmin: migrate   ## Create admin account (admin / testpass1234)
	@docker compose run -e DJANGO_SUPERUSER_EMAIL=admin@example.com \
                            -e DJANGO_SUPERUSER_PASSWORD=testpass1234 \
                            --rm backend \
                            /venv/bin/python /app/manage.py createsuperuser --username admin --no-input
logs:	## Tail the logs for backend, celeryworker, celerybeat
	@docker compose logs -f backend celeryworker celerybeat

test: .venv $(ROOT_DIR)/.env	## Run all of the tests
	@$(UV_RUN) pytest

test-frontend:	## Run the SPA unit tests (Vitest)
	@cd frontend && pnpm test

uv-sync: .venv	## Sync .venv with uv.lock after dependency changes
	@uv sync

uv-lock:	## Update uv.lock file from pyproject.toml dependencies
	@uv lock

uv-add:	## Add a new dependency (usage: make uv-add PACKAGE=requests)
	@if [ -z "$(PACKAGE)" ]; then \
		echo "Error: PACKAGE not specified. Usage: make uv-add PACKAGE=requests"; \
		exit 1; \
	fi
	@uv add $(PACKAGE)

uv-add-dev:	## Add a dev dependency (usage: make uv-add-dev PACKAGE=pytest-xdist)
	@if [ -z "$(PACKAGE)" ]; then \
		echo "Error: PACKAGE not specified. Usage: make uv-add-dev PACKAGE=pytest-xdist"; \
		exit 1; \
	fi
	@uv add --dev $(PACKAGE)

uv-upgrade:	## Upgrade all dependencies to latest compatible versions
	@uv sync --upgrade

api-schema: .venv docs	## Generate OpenAPI schema YAML into docs/openapi.yaml
	@PYTHONPATH=$(ROOT_DIR)/app $(UV_RUN) python app/manage.py spectacular --color --file docs/openapi.yaml
	@echo "OpenAPI schema written to docs/openapi.yaml"

api-docs: api-schema	## Generate API markdown docs from OpenAPI schema
	@$(UV_RUN) python app/scripts/generate_api_docs.py docs/openapi.yaml examples docs/api.md
	@echo "API docs written to docs/api.md"

docs:
	@mkdir -p $(ROOT_DIR)/docs

tag: version	## Sign and tag HEAD with the version in pyproject.toml
	@if git rev-parse "$(VERSION)" >/dev/null 2>&1; then \
	    echo "Tag '$(VERSION)' already exists (skipping 'git tag')"; \
	else \
	    git tag --sign "$(VERSION)" -m "Version $(VERSION)"; \
	    echo "Tagged with '$(VERSION)'"; \
	fi

publish-tag: tag	## Tag (if not already tagged) and push that one tag to origin
	@git push origin tag $(VERSION)

help:	## Show this help.
	@grep -hE '^[A-Za-z0-9_ \-]*?:.*##.*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-16s\033[0m %s\n", $$1, $$2}'
