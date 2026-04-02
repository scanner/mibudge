# mibudge

Personal budgeting service inspired by [Simple Bank](https://en.wikipedia.org/wiki/Simple_(bank)).

## What is this?

Simple Bank had a budgeting model that let you divide your checking account balance into virtual sub-accounts called "goals" and "expenses." When Simple shut down, nothing else replicated that experience well. mibudge is an attempt to rebuild and improve on that model for personal and family use.

### The core idea

You have one or more bank accounts. Each account's balance is divided into **budgets** and **goals** — virtual sub-accounts that live entirely inside mibudge. Every dollar in the account is allocated to one of these, with an "Unallocated" budget catching anything not yet assigned.

**Transactions** from the bank (purchases, deposits, transfers) are associated with a budget. Transactions may arrive as *pending* — recorded but not yet settled, with the final amount potentially differing from the pending amount (e.g. a gas station pre-authorization vs. the actual charge). A transaction represents one concrete bank event regardless of whether it is pending or posted. Most map to a single budget, but a transaction can be split — say, a store receipt that's part groceries and part home improvement supplies.

As money comes in (paychecks, etc.), it's automatically distributed to budgets and goals on a schedule, so that by the time a bill is due or a savings target arrives, the money is there.

### Budgets vs Goals

A **goal** has a target amount and a target date. Money accumulates on a funding schedule until the goal is reached. Once funded, it's complete.

A **budget** (recurring) is never truly complete. It has a refresh cycle — monthly, quarterly, yearly, etc. Money builds up until the target is reached, then resets on the next cycle. Think rent, groceries, subscriptions.

Recurring budgets can optionally have an associated **fill-up goal**. The fill-up goal is where automatic funding deposits go — not directly into the budget itself. Then, at the boundary between one refresh cycle and the next:

1. Money in the fill-up goal is transferred into the budget, up to the budget's target amount.
2. Any excess that doesn't fit (because the budget wasn't fully spent) stays in the fill-up goal.

For example: you have a monthly grocery budget with a $500 target. Throughout the month, automatic funding deposits accumulate in the fill-up goal. At the start of the cycle, the fill-up goal transfers $500 into the budget. You spend $400 that month. When the cycle refreshes, the $100 left in the budget doesn't need to move — the fill-up goal only needs to top the budget up to $500, so it contributes $400 instead of $500. That means the fill-up goal starts its next accumulation cycle with a $100 head start, needing only $400 in new funding to be ready for the following refresh. This also means you can have a fully funded budget that is ready to spend *while simultaneously* accumulating funds in the fill-up goal for the next cycle.

Both types can be funded automatically (calculated from schedule + target) or with a fixed amount per funding event.

### Accounts

mibudge supports multiple bank accounts — checking, savings, credit cards — each with their own set of budgets. Accounts can be shared between users (family members) or private to one user.

## Architecture

### Backend: Django + DRF

- **Python 3.13+** / **Django 6.x** / **Django REST Framework**
- **Celery** + **Redis** for async task scheduling (budget funding, etc.)
- **PostgreSQL** with psycopg (async-capable)
- **django-allauth** for authentication, **django-guardian** for object permissions
- **djmoney** MoneyField for all monetary values
- **django-recurrence** for funding/refresh schedules

### Frontend: Vue 3 SPA (planned)

- **Vue 3** + **Vite** (replaces old gulp/browsersync toolchain)
- **Pinia** for state management, **Vue Router** (history mode, base `/app/`)
- **Axios** for API client with interceptors for silent JWT token refresh
- **django-vite** for dev integration (HMR via Vite dev server)

### URL routing

| Path | Handled by | Purpose |
|------|-----------|---------|
| `/`, `/accounts/`, `/admin/` | Django templates | Login, auth, admin |
| `/api/` | DRF | JWT-authenticated REST API |
| `/app/*` | Vue SPA | Catch-all, Vue Router handles sub-routes |

### Auth: JWT two-token pattern (planned)

- **Access token** (60 min): held in JS memory only, sent as `Authorization: Bearer` header
- **Refresh token** (14 days, sliding): `httpOnly; Secure; SameSite=Strict` cookie, never readable by JS
- **Login flow**: django-allauth handles credentials, custom adapter generates JWT pair, refresh token set as httpOnly cookie, access token injected as `window.__INITIAL_TOKEN__` for SPA bootstrap

## Project structure

```
mibudge/
  app/                          # Django application code
    config/                     # Django settings, urls, asgi/wsgi, celery
    mibudge/                    # Main package
      moneypools/               # Core budgeting app (models, signals, views)
      users/                    # User model, auth adapters, API
      contrib/                  # Site migrations
      utils/                    # Context processors, helpers
    scripts/                    # Container startup scripts
      start_app.sh              # Production: collectstatic + gunicorn
      start_dev.sh              # Development: migrate + runserver_plus
      start_celeryworker.sh     # Celery worker
      start_celerybeat.sh       # Celery beat scheduler
      start_flower.sh           # Celery Flower dashboard
    manage.py
  deploy/                       # Deployment configuration
    docker-compose.prod.yml     # Production compose (stock postgres/redis)
    .env.example                # Production env template
  frontend/                     # Vue 3 SPA (planned)
  Dockerfile                    # Multi-stage: builder -> dev -> prod
  docker-compose.yml            # Local dev (django, postgres, redis, celery)
  pyproject.toml                # Dependencies, tool config (ruff, mypy, pytest)
  uv.lock                       # Locked dependencies
  Makefile                      # Dev commands (make help for full list)
  Make.rules                    # Shared make rules (lint, format, mypy)
```

### Docker

A single multi-stage `Dockerfile` produces both dev and prod images:

- **builder** — compiles Python dependencies into `/venv` using uv
- **dev** — includes dev dependencies, build tools, debugging utilities
- **prod** — minimal runtime with only production dependencies, pre-compiled bytecode

The container's `WORKDIR` is `/app`. The dev docker-compose mounts `./app:/app:z` so code changes are reflected immediately. The venv lives at `/venv` (outside the mount) so it isn't shadowed.

Startup scripts in `app/scripts/` use [wait-for-it](https://pypi.org/project/wait-for-it/) for service readiness. The docker-compose `command:` selects which script runs — `start_dev.sh` for local dev (werkzeug `runserver_plus`), `start_app.sh` for production (gunicorn with uvicorn workers).

## Development

Prerequisites: [Docker](https://docs.docker.com/get-docker/), [uv](https://docs.astral.sh/uv/), Python 3.13+

```bash
# Start all services (builds images, runs in background)
make up

# View logs
make logs

# Shell into the django container
make shell

# Django management shell (shell_plus)
make manage_shell

# Run migrations (in container)
make migrate

# Make new migrations (runs locally via uv)
make makemigrations

# Run tests (locally via uv, not in Docker)
make test

# Run linter + formatter + mypy (locally via uv)
make lint

# See all available commands
make help
```

### Dependency management

```bash
make uv-sync          # Sync .venv with uv.lock
make uv-lock          # Update uv.lock from pyproject.toml
make uv-add PACKAGE=x # Add a dependency
make uv-add-dev PACKAGE=x  # Add a dev dependency
make uv-upgrade       # Upgrade all dependencies
```

### Environment

Local dev uses a single `.env` file at the repo root (gitignored). Copy from the example and adjust if needed:

```bash
cp deploy/.env.example .env
# Edit .env — the defaults work for local Docker dev
```

## License

BSD
