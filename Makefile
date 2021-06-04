build:
	@docker compose -f ./local.yml build

start: build
	@docker compose -f ./local.yml up --remove-orphans --detach

stop:
	@docker compose -f ./local.yml down --remove-orphans

delete:
	@docker compose -f ./local.yml down --remove-orphans

restart:
	@docker compose -f ./local.yml restart

shell:
	@docker compose -f ./local.yml run --rm django /bin/bash

manage_shell:
	@docker compose -f ./local.yml run --rm django python manage.py shell_plus

migrate:
	@docker compose -f ./local.yml run --rm django python manage.py migrate

makemigrations:
	@docker compose -f ./local.yml run --rm django python manage.py makemigrations

logs:
	@docker compose -f ./local.yml logs -f -t

test:
	@docker compose -f ./local.yml run --rm django pytest -vvvv

# XXX Could use the local machine instead of docker for this.. need to
#     setup the venv make rules (because `django` requires postgres to
#     be running, etc which is not necessary just to run black)
black:
	@docker compose -f ./local.yml run --rm django black ./
