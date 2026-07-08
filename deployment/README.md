# mibudge — Deployment

## Local development

Prerequisites: Docker, `mkcert`, `pnpm`, `uv`.

```sh
# 1. Generate .env and deployment/local-dev-docker.env from their templates
make env

# 2. Start the full stack (builds images, generates TLS certs, starts Docker
#    services, then runs the Vite dev server in the foreground)
make up
```

The app is available at `https://<hostname>:8000`.  Mailpit (local SMTP
catcher) is at `http://localhost:8025`.  Flower (Celery monitor) is at
`http://localhost:5555`.

Postgres is published on `localhost:6432` and Redis on `localhost:7379` for
direct access from local tools and tests.

**Common tasks:**

```sh
make migrate        # run migrations inside the container
make test           # run pytest locally
make lint           # ruff + mypy
make logs           # tail backend and celery logs
make manage_shell   # Django shell_plus inside the container
```

---

## Server deployment (Docker Compose)

See [`docker/README.md`](docker/README.md) for full instructions covering
secret file setup, external vs bundled Postgres/Redis, stack bringup,
updates, rollback, and `SALT_KEY` rotation.
