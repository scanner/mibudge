[![Build Status](https://drone.apricot.com/api/badges/scanner/mibudge/status.svg)](https://drone.apricot.com/scanner/mibudge)

# mibudge

Personal budgeting service inspired by [Simple Bank](https://en.wikipedia.org/wiki/Simple_(bank)).

## What is this?

Simple Bank had a budgeting model that let you divide your checking account balance into virtual sub-accounts called "goals" and "expenses." When Simple shut down, nothing else replicated that experience well. mibudge is an attempt to rebuild and improve on that model.

### The core idea

You have one or more bank accounts. Each account's balance is divided into **budgets** -- virtual sub-accounts that live entirely inside mibudge. Every dollar in the account is allocated to a budget, with an "Unallocated" budget catching anything not yet assigned. Budgets come in three types: **Goal**, **Recurring** (with an optional **Associated Fill-up Goal** sub-type), and **Capped**.

**Transactions** from the bank (purchases, deposits, transfers) are associated with a budget. Transactions may arrive as *pending* -- recorded but not yet settled, with the final amount potentially differing from the pending amount (e.g. a gas station pre-authorization vs. the actual charge). A transaction represents one concrete bank event regardless of whether it is pending or posted. Most map to a single budget, but a transaction can be split -- say, a store receipt that's part groceries and part home improvement supplies.

**Internal transactions** track the movement of money between budgets within the same account. When you move $50 from "Dining Out" to "Groceries," an internal transaction records the transfer with the source budget, destination budget, amount, and resulting balances on both sides. Internal transactions are write-once -- to undo a transfer, you create a new internal transaction reversing it rather than deleting the original. In the UI, internal transactions are hidden by default to keep the transaction feed focused on real bank activity, but a toggle lets you show them when you want to see the full audit trail.

When the same real-world money movement appears on two accounts -- for example, a credit card payment that shows as a debit on checking and a credit on the card -- mibudge can link those transactions together. This cross-account linking is done opportunistically after import when both sides are present.

As money comes in (paychecks, etc.), it's automatically distributed to budgets on a schedule, so that by the time a bill is due or a savings target arrives, the money is there.

### Funding

**Funding** is the act of moving money from the "Unallocated" pool into a specific budget. It does not involve any real bank transfer -- it's a reallocation entirely within mibudge's virtual accounting.

Each budget has a **funding schedule** (e.g. weekly, bi-weekly, monthly) and either a fixed funding amount per event or an automatically calculated amount derived from the target and the time remaining. On each scheduled funding event, mibudge moves that amount out of Unallocated and into the budget.

#### The funding engine

The engine runs automatically for all accounts at **3:00 AM daily** (Celery beat task `fund_all_accounts`). It can also be triggered manually via `POST /api/v1/bank-accounts/<id>/run-funding/` (or the "Run funding now" button in the UI) or via the importer CLI with `--run-funding`. All invocation paths use the same logic and produce the same result.

The engine processes two event types:

- **Fund events** -- fire on `budget.funding_schedule`. Transfer money from Unallocated into the budget (or into its fill-up goal, for recurring-with-fill-up budgets).
- **Recur events** -- fire on `budget.recurrance_schedule` (recurring-with-fill-up only). Transfer from the fill-up goal into the recurring budget up to its target, then reset the recurring budget's cycle.

Events are collected for all active budgets in the account, sorted chronologically (fund before recur on the same day), and processed in order. This means a catch-up run after several missed cycles replays events in the same sequence they would have occurred in real time.

**Import-freshness gate:** before processing, the engine checks `account.last_posted_through`. If the latest due event falls after that date, the entire run is deferred and no transfers are made. This prevents the engine from funding against stale transaction data.

**Empty Unallocated -- retry behavior:** if Unallocated is at $0 when a fund event fires, the event is skipped and a warning is recorded, but the budget's `last_funded_on` pointer is *not* advanced. The event will be retried on the next funding run once money has arrived. The same applies to recur events when the fill-up goal is empty.

**Partial cap:** if a fill-up goal has some money but not enough to fully fund all pending recur events, the partial amount transfers and the pointer advances. The recurring budget may be underfunded for the current cycle; it is the user's responsibility to add more money.

**Paused budgets:** funding events for a paused budget are skipped, but the budget's pointer is advanced to the event date. When the budget is unpaused, it starts fresh from the current date rather than replaying missed events.

**Result:** the engine returns a `FundingReport` with the number of transfers made, any warnings (e.g. insufficient Unallocated), and a list of skipped budget names. The UI shows this result after each manual run, including the date of the next scheduled funding event when nothing was due.

#### Importing and funding

The transaction importer (`importers/import_transactions.py`) does **not** trigger funding automatically. After importing, run funding explicitly with the `--run-funding` flag:

```bash
python import_transactions.py ... --run-funding
```

Without `--run-funding`, the import only updates transaction data and advances `last_posted_through`. The `--run-funding` flag is silently ignored on `--dry-run` imports.

### Budget types

All virtual sub-accounts are **budgets**. They differ by `budget_type`:

A **Goal** budget has a target amount and accumulates money on a funding schedule until the goal is reached. Once funded, it's marked complete -- the money sits there until you spend it or roll it into something else. Funding can be calculated automatically from a target date (mibudge works out how much each funding event must contribute given the time remaining and the current balance) or set as a fixed amount per funding event.

A **Recurring** budget is never truly complete. It has a recurrence schedule -- monthly, quarterly, yearly, etc. Money builds up until the target is reached, then resets on the next cycle. Think rent, groceries, subscriptions.

A recurring budget can optionally have an **Associated Fill-up Goal** budget. The fill-up goal is where automatic funding deposits go -- not directly into the recurring budget itself. Then, at the boundary between one recurrence cycle and the next:

1. Money in the fill-up goal is transferred into the recurring budget, up to the budget's target amount.
2. Any excess that doesn't fit (because the recurring budget wasn't fully spent) stays in the fill-up goal.

For example: you have a monthly grocery budget with a $500 target. Throughout the month, automatic funding deposits accumulate in the fill-up goal. At the start of the cycle, the fill-up goal transfers $500 into the recurring budget. You spend $400 that month. When the cycle refreshes, the $100 left in the budget doesn't need to move -- the fill-up goal only needs to top the budget up to $500, so it contributes $400 instead of $500. That means the fill-up goal starts its next accumulation cycle with a $100 head start, needing only $400 in new funding to be ready for the following refresh. This also means you can have a fully funded recurring budget that is ready to spend *while simultaneously* accumulating funds in the fill-up goal for the next cycle.

A **Capped** budget tops itself up to a fixed cap amount on a funding schedule. Each funding event deposits a fixed amount (up to the cap) into the budget; when the balance is already at or above the cap, no funding occurs. As soon as spending brings the balance below the cap, the next scheduled funding event resumes automatically. Unlike a Goal (which is complete once funded) or a Recurring budget (which resets on a cycle), a Capped budget is perpetual -- it is marked complete only while its balance equals or exceeds the cap, and reverts to active the moment any spending draws it down. Think of it as a reservoir that stays full as long as you keep it topped up: an emergency buffer, a standing household expense fund, or any amount you always want available.

### Budget lifecycle

Budgets are never hard-deleted once they have transaction history. The rule is:

- **Delete**: only allowed if the budget has no transaction allocations at all (i.e., it was created by mistake and never used). The API returns 400 if you attempt to delete a budget that has allocations.
- **Archive**: the correct way to retire a budget. Archiving moves any remaining balance to the Unallocated budget via an internal transaction, marks the budget hidden, and records `archived_at`. If the budget has an associated fill-up goal, that is archived and drained first. Archived budgets retain their full transaction history and can be retrieved via the API with `archived=true`.

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
| `/api/v1/`                   | DRF                      | JWT-authenticated REST API (v1)              |
| `/api/token/`                | `TokenObtainPairView`    | JWT access+refresh pair (cross-version)      |
| `/api/token/refresh/`        | `CookieTokenRefreshView` | Silent token refresh via httpOnly cookie     |
| `/api/v1/schema/`            | drf-spectacular          | OpenAPI schema for v1 (YAML)                 |
| `/api/v1/schema/swagger-ui/` | drf-spectacular          | Swagger UI (interactive docs)                |
| `/api/v1/schema/redoc/`      | drf-spectacular          | ReDoc (interactive docs)                     |
| `/app/*`                     | `SpaShellView`           | SPA shell; Vue Router handles all sub-routes |

### REST API resources

All resources are under `/api/v1/`. Full endpoint docs: [`docs/api.md`](docs/api.md) · OpenAPI schema: [`docs/openapi.yaml`](docs/openapi.yaml) (regenerate with `make api-docs`).

| Resource | Endpoint | Notes |
|----------|----------|-------|
| Users | `/api/v1/users/` | List/update restricted to staff; `/me/` available to all |
| Banks | `/api/v1/banks/` | Read-only reference data |
| Bank Accounts | `/api/v1/bank-accounts/` | Scoped to account owners |
| Budgets | `/api/v1/budgets/` | Scoped to account owners |
| Transactions | `/api/v1/transactions/` | Scoped to account owners |
| Allocations | `/api/v1/allocations/` | Budget assignments for transactions |
| Internal Transactions | `/api/v1/internal-transactions/` | Budget-to-budget transfers |

All resources except Banks and Users are scoped to bank account ownership -- only members of an account's `owners` M2M can access that account's data. Staff and superuser status does **not** bypass ownership checks in the REST API.

### Data management

- [`docs/importers.md`](docs/importers.md) -- REST API tools for importing bank statements and backfilling budget allocations (no server access required)
- [`docs/management-commands.md`](docs/management-commands.md) -- Django management commands for service operations, backup/restore, and data correction (requires server access)

### Auth: JWT two-token pattern

- **Access token** (60 min): held in JS memory only, sent as `Authorization: Bearer` header
- **Refresh token** (14 days, sliding): `httpOnly; Secure; SameSite=Strict` cookie, never readable by JS
- **Rotation**: `ROTATE_REFRESH_TOKENS = True`, `BLACKLIST_AFTER_ROTATION = True` -- each refresh call resets the 14-day clock
- **Login flow**: the SPA owns its own auth UI at `/app/login/`. It posts
  username+password to `POST /api/token/` (`CookieTokenObtainPairView`), which
  returns the access token in the JSON body and sets the refresh token as the
  `httpOnly; Secure; SameSite=Strict` cookie.
- **Cold-boot silent refresh**: on first load, `main.ts` calls
  `authStore.refresh()` before installing the router. If the refresh cookie is
  still valid, the SPA becomes authenticated before the first route guard runs
  and returning users skip the login screen entirely.
- **Silent refresh on 401**: when the access token expires, the auth store
  calls `POST /api/token/refresh/` -- the browser sends the httpOnly cookie
  automatically, returning a new access token and rotating the refresh cookie.
- **django-allauth**: remains mounted at `/accounts/` for password reset flows
  only; it is not part of the SPA login path. See
  `task-mibudge-crispy-allauth` for the follow-up work required before the
  allauth templates can render.

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
    templates/            # Django templates: SPA shell, allauth overrides
    static/               # Static files served by Django
  frontend/               # Vue 3 SPA
    src/                  # TypeScript source: components, Pinia stores, Vue Router, API client
    dist/                 # Production build output (collected by Django staticfiles)
  deployment/             # Dev and prod docker env files, SSL certs, DB backups
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

Local dev uses **two** env files with distinct purposes:

| File | Read by | Contains |
|------|---------|----------|
| `.env` (repo root, gitignored) | Local shell — `uv run manage.py`, `pytest`, linters, `make api-schema` | `localhost` URLs with published ports |
| `deployment/local-dev-docker.env` (gitignored) | docker-compose (`env_file:`) | Docker-internal hostnames and port numbers |

The split lets you run `app/manage.py` directly from the native shell without docker-execing into a container, while docker-compose services still talk to each other over the docker network.

**Published ports** (docker → localhost):

| Service | docker-internal | localhost |
|---------|----------------|-----------|
| PostgreSQL | `postgres:5432` | `localhost:6432` |
| Redis | `redis:6379` | `localhost:7379` |
| Mailpit SMTP | `mailpit:1025` | `localhost:1025` |

**First-time setup:**

```bash
# Create .env from the template (only needed once; edit after if needed)
make env
```

`make env` generates both files from their committed templates if they do not already exist: `deployment/dot-env.dev` → `.env`, and `deployment/dot-env.docker-dev` → `deployment/local-dev-docker.env`. The defaults in both templates work without any edits for a standard local dev setup.

## License

BSD
