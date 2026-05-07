# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**mibudge** is a personal budgeting web service (inspired by Simple Bank's virtual envelope budgeting). It is a Django 5.2 backend with a Vue 3 TypeScript SPA frontend, deployed via Docker Compose.

---

## Commands

### Python / Django (backend)

All Python commands use `uv` for dependency management. The full dev stack runs in Docker; test/lint run locally.

```bash
make up             # Build and start all Docker services (Django, Postgres, Redis, Celery, Mailpit)
make down           # Stop all services
make purge          # Destroy all volumes (resets DB)
make logs           # Tail backend + celery logs
make migrate        # Run migrations inside the container
make makemigrations # Generate migrations locally via uv
make shell          # Bash into the backend container
make manage_shell   # Django shell_plus inside the container

make test           # Run pytest locally (not inside Docker)
make lint           # Run ruff formatter + linter + mypy locally
```

Generating API docs (re-run whenever the REST API changes):

```bash
make api-schema   # Generate docs/openapi.yaml via manage.py spectacular
make api-docs     # Generate docs/api.md from the OpenAPI schema
```

Interactive API docs (when the dev server is running):
- Swagger UI: `/api/v1/schema/swagger-ui/`
- ReDoc: `/api/v1/schema/redoc/`

Running a single test file or test case:

```bash
uv run pytest app/tests/moneypools/test_models.py -v
uv run pytest app/tests/moneypools/test_models.py::TestBudget::test_create_budget -v
```

Dependency management:

```bash
make uv-sync            # Sync .venv with uv.lock
make uv-add PACKAGE=x   # Add production dependency
make uv-add-dev PACKAGE=x  # Add dev dependency
```

### Frontend (Vue 3 / Vite)

Frontend dependencies use `pnpm`. Source is in `frontend/`.

```bash
cd frontend
pnpm install      # Install dependencies
pnpm dev          # Vite dev server on :5173 (HMR)
pnpm build        # Production build → frontend/dist/
pnpm type-check   # vue-tsc
pnpm fmt          # Format with oxfmt
```

---

## Architecture

### Backend (`app/`)

Django project root is `app/`. Settings live in a single file `app/config/settings.py` (all env-var based, no separate prod/dev files). The DRF router is in `app/config/api_router.py`; all versioned REST endpoints are mounted at `/api/v1/`. The per-app module path mirrors the URL: each Django app owns an `api/v1/` subpackage for its v1 views/serializers/filters, and a future v2 would live alongside as `api/v2/`. Cross-version endpoints (JWT auth) stay flat at `/api/token/...`.

**Django apps:**

- **`moneypools/`** — core budgeting domain (see Models below)
- **`users/`** — custom user model (`AbstractUser` + `name` field), JWT auth views, allauth integration

**URL routing summary:**

| Path | Handler |
|------|---------|
| `/admin/` | Django admin (URL configurable via `DJANGO_ADMIN_URL` env var) |
| `/accounts/` | django-allauth (password reset only; SPA owns login at `/app/login/`; registration disabled by default) |
| `/api/v1/` | DRF REST API v1 (JWT-authenticated) |
| `/api/token/` | `TokenObtainPairView` — JWT access+refresh pair (cross-version) |
| `/api/token/refresh/` | `CookieTokenRefreshView` — silent JWT refresh from httpOnly cookie (cross-version) |
| `/api/v1/schema/` | drf-spectacular — OpenAPI schema for v1 (YAML) |
| `/api/v1/schema/swagger-ui/` | drf-spectacular — Swagger UI (interactive docs) |
| `/api/v1/schema/redoc/` | drf-spectacular — ReDoc (interactive docs) |
| `/app/*` | `SpaShellView` — serves `index.html`; Vue Router handles all sub-routes |

### Authentication

Two-token JWT pattern:
- **Access token**: short-lived (60 min), stored in JS memory only, sent as `Authorization: Bearer` header.
- **Refresh token**: long-lived (14 days sliding), httpOnly cookie, refreshed via `/api/token/refresh/`.

The Vue `auth` Pinia store manages the access token lifecycle and provides an authenticated `apiFetch` wrapper that silently refreshes before expiry.

### Core Models (`moneypools/`)

All models extend `MoneyPoolBaseClass` (abstract), which provides `pkid` (BigAutoField PK), `id` (UUID), and `created_at`/`modified_at` timestamps.

- **`Bank`** — financial institution (name, routing number, default currency).
- **`BankAccount`** — checking/savings/credit card account; has `posted_balance` and `available_balance` (both `MoneyField`); M2M to `User`; FK to `auth.Group` for joint accounts; a signal auto-creates an "Unallocated" budget on creation.
- **`Budget`** — virtual envelope (Goal / Recurring / Recurring-with-fill-up-goal types); has target amount, target date, and a `recurrence` funding schedule; signals handle automatic funding.
- **`Transaction`** — bank event (purchase or deposit); has `pending`/`posted` status. Has an optional `linked_transaction` OneToOneField for pairing counterpart transactions across accounts (e.g. credit card payment on checking linked to the corresponding credit on the card). Links are populated opportunistically by the import pipeline.
- **`InternalTransaction`** — budget-to-budget transfer within the same bank account (write-once). Records src/dst budget with balance snapshots. Users undo transfers by creating a reversing InternalTransaction, not by deleting. Hidden by default in the UI with a toggle to show.
- **`TransactionAllocation`** — maps a portion of a Transaction's amount to a Budget. Every transaction has at least one allocation; split transactions have multiple allocations summing to the transaction total. Budget balance adjustments flow through allocations.
- **`TransactionCategory`** — `TextChoices` enum with 100+ categories.

Money values everywhere use `djmoney` `MoneyField` (14 digits, 2 decimal places, USD default). Sensitive fields (e.g., account numbers) use `django-fernet-encrypted-fields` with `SALT_KEY` rotation support.

### API Permissions

- **Banks**: read-only, any authenticated user.
- **Users**: list/retrieve/update restricted to staff; `/api/v1/users/me/` available to all authenticated users.
- **All other resources** (bank accounts, budgets, transactions, allocations, internal transactions): scoped to bank account ownership via `IsAccountOwner` permission and `AccountOwnerQuerySetMixin`. Only users in an account's `owners` M2M can access that account and its related objects. Staff and superuser status does **not** bypass ownership checks in the REST API (the django-admin is a separate access path).

### Async / Scheduled Work

Celery + Redis for async tasks; `django-celery-beat` for periodic scheduling (database-backed). Use cases: automatic budget funding resets, recurring budget allocation. Flower (port 5555) provides a Celery monitoring UI.

Periodic tasks that should be defined in code (not created ad-hoc via the admin) go in `MANAGED_PERIODIC_TASKS` in `app/config/celery_app.py`. On beat startup, `sync_periodic_tasks()` reconciles the registry against the database: it creates missing tasks, updates changed ones, and deletes any with the `[managed] ` prefix that are no longer in the registry. Admin-created tasks (without that prefix) are never touched. Each entry takes a `task` dotted path, a `schedule` dict (either `{"every": N, "period": "..."}` for an interval or `{"crontab": {...}}` for a crontab), and optional `args`, `kwargs`, and `enabled` keys.

### Frontend (`frontend/`)

- **Vue 3 + TypeScript (strict)**, Vite, Pinia, Vue Router
- API calls use native `fetch` (no axios); the auth Pinia store's `apiFetch` wraps requests with JWT auth and transparent refresh.
- In development, Vite runs at `:5173` and `django-vite` proxies asset requests. In production, Vite outputs `frontend/dist/` with a `manifest.json`; `collectstatic` picks it up and `django-vite` injects hashed filenames into Django templates.

### Tests (`app/tests/`)

Tests are centralized in `app/tests/` (mirroring app structure). Uses `pytest-django`, `factory-boy` (with `pytest-factoryboy`), `faker`, `freezegun`, `fakeredis`, and `pytest-mock`. All test DB access requires `@pytest.mark.django_db`.

#### Factory pattern -- IMPORTANT

Factories live in `app/tests/<app>/factories.py`. Each factory is registered in
`app/tests/<app>/conftest.py` via `pytest_factoryboy.register()`, which exposes
a callable fixture named after the factory in snake_case:

```python
# conftest.py
from pytest_factoryboy import register
from .factories import BankFactory, BankAccountFactory

register(BankFactory)        # -> bank_factory fixture
register(BankAccountFactory) # -> bank_account_factory fixture
```

**Always use the `*_factory` fixtures in tests -- never call `BankFactory()`
directly.** Direct factory calls bypass pytest-factoryboy's fixture scoping and
produce mypy errors (`"BankFactory" has no attribute "id"`, etc.) because
factory-boy's type stubs don't reflect the generated model instances.

The fixture is a `Callable[..., <Model>]` that accepts the same keyword
arguments as the factory. The mypy annotation is:

```python
from collections.abc import Callable
from moneypools.models import Bank, BankAccount

def test_something(
    bank_factory: Callable[..., Bank],
    bank_account_factory: Callable[..., BankAccount],
) -> None:
    bank = bank_factory()                        # Bank instance, fully typed
    account = bank_account_factory(owners=[user]) # keyword args passed through
```

The one exception: `@pytest.mark.parametrize` class-level decorators run before
fixtures are resolved, so factory classes must be imported directly when used in
parametrize arguments. Add a comment explaining why:

```python
# Direct factory imports needed here because @pytest.mark.parametrize
# arguments are evaluated before pytest fixtures are resolved.
from tests.moneypools.factories import BankFactory, BankAccountFactory

@pytest.mark.parametrize("factory_cls", [BankFactory, BankAccountFactory])
def test_something(factory_cls) -> None: ...
```

### Code Quality

- **Python**: ruff (formatter + linter, line-length 80) + mypy. `make lint` runs all three.
- **Frontend**: oxfmt (formatter), vue-tsc (type checking).
- **Pre-commit hooks**: configured in `.pre-commit-config.yaml`.

The mypy config disables the `django-manager-missing` error due to a `django-money` compatibility issue.

### Environment

Local dev uses **two** env files:

- **`.env`** (repo root, gitignored) — read by the local shell (`uv run manage.py`, `pytest`, linters). Uses `localhost` with published ports: postgres on `localhost:6432`, redis on `localhost:7379`. Generate with `make env` (copies `deployment/dot-env.dev`).
- **`deployment/local-dev-docker.env`** (gitignored) — read by docker-compose via `env_file:`. Uses docker-internal hostnames (`postgres`, `redis`) and internal port numbers. Generate with `make env` (copies `deployment/dot-env.docker-dev`).

Key variables (both files): `DEBUG`, `DJANGO_SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL`, `SALT_KEY`.
