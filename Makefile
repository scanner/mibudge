# -*- Mode: Makefile -*-
ROOT_DIR := $(shell git rev-parse --show-toplevel)
include $(ROOT_DIR)/Make.rules

DOCKER_BUILDKIT := 1

# Ephemeral salt used only during `collectstatic` at image build time.
# Never baked into the image as an ENV var; the real SALT_KEY is injected
# at runtime via .env / docker-compose.
BUILD_SALT_KEY := $(shell openssl rand -hex 32)

.PHONY: clean purge test logs migrate makemigrations createadmin manage_shell shell restart down up build env uv-sync uv-lock uv-add uv-add-dev uv-upgrade api-schema api-docs help

env: $(ROOT_DIR)/.env	## Copy deployment/dot-env.dev to .env if it does not exist

$(ROOT_DIR)/.env:
	@cp $(ROOT_DIR)/deployment/dot-env.dev $(ROOT_DIR)/.env
	@echo "Created .env from deployment/dot-env.dev"

build:	## Build prod and dev Docker images
	@COMPOSE_DOCKER_CLI_BUILD=1 DOCKER_BUILDKIT=1 docker build --build-arg PYTHON_VERSION="$(PYTHON_VERSION)" --build-arg SALT_KEY="$(BUILD_SALT_KEY)" --target prod --tag mibudge:latest .
	@COMPOSE_DOCKER_CLI_BUILD=1 DOCKER_BUILDKIT=1 docker build --build-arg PYTHON_VERSION="$(PYTHON_VERSION)" --build-arg SALT_KEY="$(BUILD_SALT_KEY)" --target dev --tag mibudge:dev .

dirs: dbs ssl     ## Make the local directories for dbs, ssl, etc.

dbs:
	@mkdir -p $(ROOT_DIR)/deployment/db_backups

ssl:
	@mkdir -p $(ROOT_DIR)/deployment/ssl

deployment/ssl/ssl_key.pem deployment/ssl/ssl_crt.pem: | ssl
	@mkcert -key-file $(ROOT_DIR)/deployment/ssl/ssl_key.pem \
                -cert-file $(ROOT_DIR)/deployment/ssl/ssl_crt.pem \
                `hostname` localhost 127.0.0.1 ::1

certs: ssl deployment/ssl/ssl_key.pem deployment/ssl/ssl_crt.pem	## uses `mkcert` to create certificates for local development.

up: build dirs certs	## Build and docker compose up
	@docker compose up --remove-orphans --detach

down:	## docker compose down
	@docker compose down --remove-orphans

purge:	## docker compose down, removing all volumes (destroys db data)
	@docker compose down --remove-orphans --volumes

restart:	## docker compose restart
	@docker compose restart

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
	@$(UV_RUN) python app/scripts/generate_api_docs.py docs/openapi.yaml docs/api.md
	@echo "API docs written to docs/api.md"

docs:
	@mkdir -p $(ROOT_DIR)/docs

help:	## Show this help.
	@grep -hE '^[A-Za-z0-9_ \-]*?:.*##.*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-16s\033[0m %s\n", $$1, $$2}'
