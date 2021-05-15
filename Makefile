local_build:
	@docker compose -f ./local.yml build

local_start: local_build
	@docker compose -f ./local.yml up --remove-orphans --detach

local_stop:
	@docker compose -f ./local.yml down --remove-orphans

local_delete:
	@docker compose -f ./local.yml down --remove-orphans

local_restart:
	@docker compose -f ./local.yml restart

local_shell:
	@docker compose -f ./local.yml run --rm /bin/bash

local_manage_shell:
	@docker compose -f ./local.yml run --rm django python manage.py shell_plus

local_migrate:
	@docker compose -f ./local.yml run --rm django python manage.py migrate

local_makemigrations:
	@docker compose -f ./local.yml run --rm django python manage.py makemigrations

local_logs:
	@docker compose -f ./local.yml logs -f -t

test:
	@docker compose -f ./local.yml run --rm django pytest
