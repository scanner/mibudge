# -*- Mode: Makefile -*-
ROOT_DIR := $(shell git rev-parse --show-toplevel)
include $(ROOT_DIR)/Make.rules

DOCKER_BUILDKIT := 1

.PHONY: clean test logs migrate makemigrations manage_shell shell restart down up build uv-sync uv-lock uv-add uv-add-dev uv-upgrade help

build:	## Build prod and dev Docker images
	@COMPOSE_DOCKER_CLI_BUILD=1 DOCKER_BUILDKIT=1 docker build --build-arg PYTHON_VERSION="$(PYTHON_VERSION)" --target prod --tag mibudge:latest .
	@COMPOSE_DOCKER_CLI_BUILD=1 DOCKER_BUILDKIT=1 docker build --build-arg PYTHON_VERSION="$(PYTHON_VERSION)" --target dev --tag mibudge:dev .

up: build	## Build and docker compose up
	@docker compose up --remove-orphans --detach

down:	## docker compose down
	@docker compose down --remove-orphans

restart:	## docker compose restart
	@docker compose restart

shell:	## Make a bash shell in an ephemeral django container
	@docker compose run --rm django /bin/bash

manage_shell:	## Run manage.py shell_plus in a django container
	@docker compose run --rm django python manage.py shell_plus

migrate:	## Run manage.py migrate
	@docker compose run --rm django python manage.py migrate

makemigrations:	## Run manage.py makemigrations
	@PYTHONPATH=$(ROOT_DIR)/app $(UV_RUN) python app/manage.py makemigrations

logs:	## Tail the logs for django, celeryworker, celerybeat
	@docker compose logs -f django celeryworker celerybeat

test: .venv	## Run all of the tests
	@$(UV_RUN) pytest app/

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

help:	## Show this help.
	@grep -hE '^[A-Za-z0-9_ \-]*?:.*##.*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-16s\033[0m %s\n", $$1, $$2}'
