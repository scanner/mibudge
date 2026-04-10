[![Build Status](https://drone.apricot.com/api/badges/scanner/mibudge/status.svg)](https://drone.apricot.com/scanner/mibudge)

# mibudge

Personal budgeting service inspired by [Simple Bank](https://en.wikipedia.org/wiki/Simple_(bank)).

## What is this?

Simple Bank had a budgeting model that let you divide your checking account balance into virtual sub-accounts called "goals" and "expenses." When Simple shut down, nothing else replicated that experience well. mibudge is an attempt to rebuild and improve on that model for personal and family use.

### The core idea

You have one or more bank accounts. Each account's balance is divided into **budgets** -- virtual sub-accounts that live entirely inside mibudge. Every dollar in the account is allocated to a budget, with an "Unallocated" budget catching anything not yet assigned. Budgets come in two types: **Goal** and **Recurring** (with an optional **Associated Fill-up Goal** sub-type tied to a recurring budget).

**Transactions** from the bank (purchases, deposits, transfers) are associated with a budget. Transactions may arrive as *pending* -- recorded but not yet settled, with the final amount potentially differing from the pending amount (e.g. a gas station pre-authorization vs. the actual charge). A transaction represents one concrete bank event regardless of whether it is pending or posted. Most map to a single budget, but a transaction can be split -- say, a store receipt that's part groceries and part home improvement supplies.

As money comes in (paychecks, etc.), it's automatically distributed to budgets on a schedule, so that by the time a bill is due or a savings target arrives, the money is there.

### Funding

**Funding** is the act of moving money from the "Unallocated" pool into a specific budget. It does not involve any real bank transfer -- it's a reallocation entirely within mibudge's virtual accounting.

Each budget has a **funding schedule** (e.g. weekly, bi-weekly, monthly) and either a fixed funding amount per event or an automatically calculated amount derived from the target and the time remaining. On each scheduled funding event, mibudge moves that amount out of Unallocated and into the budget. If Unallocated doesn't have enough to cover all scheduled funding events, those events are partially funded or deferred.

### Budget types

All virtual sub-accounts are **budgets**. They differ by `budget_type`:

A **Goal** budget has a target amount and a target date. Money accumulates on a funding schedule until the goal is reached. Once funded, it's complete -- the money sits there until you spend it or roll it into something else.

A **Recurring** budget is never truly complete. It has a recurrence schedule -- monthly, quarterly, yearly, etc. Money builds up until the target is reached, then resets on the next cycle. Think rent, groceries, subscriptions.

A recurring budget can optionally have an **Associated Fill-up Goal** budget. The fill-up goal is where automatic funding deposits go -- not directly into the recurring budget itself. Then, at the boundary between one recurrence cycle and the next:

1. Money in the fill-up goal is transferred into the recurring budget, up to the budget's target amount.
2. Any excess that doesn't fit (because the recurring budget wasn't fully spent) stays in the fill-up goal.

For example: you have a monthly grocery budget with a $500 target. Throughout the month, automatic funding deposits accumulate in the fill-up goal. At the start of the cycle, the fill-up goal transfers $500 into the recurring budget. You spend $400 that month. When the cycle refreshes, the $100 left in the budget doesn't need to move -- the fill-up goal only needs to top the budget up to $500, so it contributes $400 instead of $500. That means the fill-up goal starts its next accumulation cycle with a $100 head start, needing only $400 in new funding to be ready for the following refresh. This also means you can have a fully funded recurring budget that is ready to spend *while simultaneously* accumulating funds in the fill-up goal for the next cycle.

All budget types can be funded automatically (calculated from schedule + target) or with a fixed amount per funding event.

### Accounts

mibudge supports multiple bank accounts -- checking, savings, credit cards -- each with their own set of budgets. Accounts can be shared between users (family members) or private to one user.

## Architecture

### Backend: Django + DRF

- **Python 3.13+** / **Django 5.2 LTS** / **Django REST Framework**
- **djangorestframework-simplejwt** for JWT authentication
- **Celery** + **Redis** for async task scheduling (budget funding, etc.)
- **PostgreSQL** with psycopg (async-capable)
- **django-allauth** for authentication (closed registration by default), **django-guardian** for object permissions
- **djmoney** MoneyField for all monetary values
- **django-recurrence** for funding/refresh schedules

### Frontend: Vue 3 SPA

- **Vue 3** + **Vite** with **TypeScript** throughout
- **Pinia** for state management, **Vue Router** (history mode, base `/app/`)
- Native `fetch` wrapper (`src/api/client.ts`) -- no third-party HTTP client
- **django-vite** for dev integration (HMR via Vite dev server)
- Build output: `frontend/dist/` collected by Django staticfiles for production

### URL routing

| Path                         | Handled by               | Purpose                                      |
|------------------------------|--------------------------|----------------------------------------------|
| `/`, `/accounts/`, `/admin/` | Django templates         | Login, auth, admin                           |
| `/api/`                      | DRF                      | JWT-authenticated REST API                   |
| `/api/token/refresh/`        | `CookieTokenRefreshView` | Silent token refresh via httpOnly cookie     |
| `/api/schema/`               | drf-spectacular          | OpenAPI schema (YAML)                        |
| `/api/schema/swagger-ui/`    | drf-spectacular          | Swagger UI (interactive docs)                |
| `/api/schema/redoc/`         | drf-spectacular          | ReDoc (interactive docs)                     |
| `/app/*`                     | `SpaShellView`           | SPA shell; Vue Router handles all sub-routes |

The machine-readable OpenAPI spec and generated API reference docs live in [`docs/openapi.yaml`](docs/openapi.yaml) and [`docs/api.md`](docs/api.md). Regenerate them after any API change with `make api-docs`.

### Auth: JWT two-token pattern

- **Access token** (60 min): held in JS memory only, sent as `Authorization: Bearer` header
- **Refresh token** (14 days, sliding): `httpOnly; Secure; SameSite=Strict` cookie, never readable by JS
- **Rotation**: `ROTATE_REFRESH_TOKENS = True`, `BLACKLIST_AFTER_ROTATION = True` -- each refresh call resets the 14-day clock
- **Login flow**:
  1. django-allauth handles credentials at `/accounts/login/`
  2. `LOGIN_REDIRECT_URL` sends the authenticated user to `SpaLoginView`
  3. `SpaLoginView` issues a JWT pair, sets the refresh token as an httpOnly cookie, and renders a minimal handoff page
  4. The handoff page sets `window.__INITIAL_TOKEN__` and immediately redirects to `/app/`
  5. The Vue SPA reads the token once into the Pinia auth store and removes it from `window`
- **Silent refresh**: when the access token expires the auth store calls `POST /api/token/refresh/` -- the browser sends the httpOnly cookie automatically, returning a new access token and rotating the refresh cookie

## Project structure

```
mibudge/
  app/                    # Django project root (WORKDIR /app in container)
    config/               # Django settings, root URL conf, Celery app, DRF router
    users/                # Custom user app: model, views, URLs, allauth adapters, DRF API
    moneypools/           # Core budgeting app: models, signals, views
    tests/                # All tests, separated from app code by Django app
      config/             # Config and URL-level tests
      users/              # User app tests and model factories
      moneypools/         # Moneypools tests and model factories
    scripts/              # Container startup scripts (one per service: app, celery worker,
                          #   celery beat, flower). Selected via docker-compose `command:`
    templates/            # Django templates: SPA shell, JWT handoff page, allauth overrides
    static/               # Static files served by Django
  frontend/               # Vue 3 SPA
    src/                  # TypeScript source: components, Pinia stores, Vue Router, API client
    dist/                 # Production build output (collected by Django staticfiles)
  deploy/                 # Production docker-compose and environment config
  Dockerfile              # Multi-stage build: builder → dev → prod
  docker-compose.yml      # Local dev stack (Django, Postgres, Redis, Celery)
  Makefile                # Dev commands (`make help` for full list)
```

### Docker

A single multi-stage `Dockerfile` produces both dev and prod images:

- **builder** -- compiles Python dependencies into `/venv` using uv
- **dev** -- includes dev dependencies, build tools, debugging utilities
- **prod** -- minimal runtime with only production dependencies, pre-compiled bytecode

The container's `WORKDIR` is `/app`. The dev docker-compose mounts `./app:/app:z` so code changes are reflected immediately. The venv lives at `/venv` (outside the mount) so it isn't shadowed.

Startup scripts in `app/scripts/` use [wait-for-it](https://pypi.org/project/wait-for-it/) for service readiness. The docker-compose `command:` selects which script runs -- `start_dev.sh` for local dev (uvicorn --reload), `start_app.sh` for production (gunicorn with uvicorn workers).

## Development

Prerequisites: [Docker](https://docs.docker.com/get-docker/), [uv](https://docs.astral.sh/uv/), Python 3.13+, [pnpm](https://pnpm.io/)

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

### Frontend development

```bash
cd frontend
pnpm install      # Install dependencies
pnpm dev          # Start Vite dev server (port 5173, HMR enabled)
pnpm build        # Production build → frontend/dist/
pnpm type-check   # Run vue-tsc
```

Set `DJANGO_VITE_DEV_MODE=True` in your `.env` (or rely on the `DEBUG=True` default) so Django proxies asset requests to the Vite dev server during development.

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
# Edit .env -- the defaults work for local Docker dev
```

## License

BSD
