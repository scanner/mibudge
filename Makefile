ROOT_DIR := $(shell git rev-parse --show-toplevel)
include $(ROOT_DIR)/Make.rules

.PHONY: clean lint test logs migrate makemigrations manage_shell shell start stop build

build:
	@docker compose -f ./docker-compose.yml build

start: build
	@docker compose -f ./docker-compose.yml up --remove-orphans --detach

stop:
	@docker compose -f ./docker-compose.yml down --remove-orphans

shell:
	@docker compose -f ./docker-compose.yml run --rm django /bin/bash

manage_shell:
	@docker compose -f ./docker-compose.yml run --rm django python manage.py shell_plus

migrate:
	@docker compose -f ./docker-compose.yml run --rm django python manage.py migrate

makemigrations:
	@docker compose -f ./docker-compose.yml run --rm django python manage.py makemigrations

logs:
	@docker compose -f ./docker-compose.yml logs -f -t

test:
	@docker compose -f ./docker-compose.yml run --rm django pytest --disable-warnings -vvvv

# Dependency management
uv-sync: .venv
uv-lock:
	@uv lock
uv-add:
	@uv add $(PACKAGE)
