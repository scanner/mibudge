# mibudge — Production Deployment (Docker Compose)

This directory is a complete deployment of mibudge with Docker Compose, for
production, staging or integration hosts. Copy it to the host, fill in `.env`
and `secrets/`, and start it. Nothing here is used by local development (see
[`../README.md`](../README.md)).

The stack pulls a pre-built image from GHCR (`ghcr.io/scanner/mibudge`),
published for `linux/amd64` and `linux/arm64`, and expects PostgreSQL and Redis to be available, either as external services
connected via Docker networks or bundled into this Compose file.

---

## Directory layout

```
deployment/production/
  docker-compose.yml    # app stack (web, celeryworker, celerybeat, migrate)
  dot-env.example       # non-secret config template — copy to .env
  secrets/              # credential files (gitignored except .gitkeep)
  README.md             # this file
```

---

## 1. Create secret files

Each file holds one value with no trailing newline. Create them under
`secrets/`:

```sh
# Full Postgres connection URL including credentials
printf 'postgres://mibudge:YOURPASSWORD@postgres:5432/mibudge' > secrets/database_url

# Django signing key — generate with:
#   python -c "import secrets; print(secrets.token_hex(50), end='')"
printf 'YOURKEY' > secrets/django_secret_key

# Fernet encryption key for sensitive fields — generate with:
#   python -c "import secrets; print(secrets.token_hex(32), end='')"
printf 'YOURKEY' > secrets/salt_key

# SMTP credentials
printf 'smtp-user@example.com' > secrets/email_host_user
printf 'YOURPASSWORD'          > secrets/email_host_password
```

`printf` (not `echo`) avoids the trailing newline that most editors append.

---

## 2. Configure .env

```sh
cp dot-env.example .env
$EDITOR .env
```

Set at minimum: `VERSION`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`,
`SITE_URL`, `DJANGO_ADMIN_URL`, `EMAIL_HOST`, `REDIS_URL`,
`CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`.

---

## 3. PostgreSQL and Redis

The app stack connects to Postgres and Redis over Docker networks. Choose one
of the two approaches below.

### Option A — External services (recommended for production)

Run Postgres and Redis as separate stacks. Each stack creates a named Docker
network that the app stack joins as an external network.

**Postgres** — using the
[`postgres-docker-compose`](https://github.com/scanner/postgres-docker-compose)
template:

```sh
# On the same host, in the postgres stack directory:
docker compose up -d
# This creates the `postgres_net` network.
```

**Redis** — example minimal stack:

```sh
# redis/docker-compose.yml
# services:
#   redis:
#     image: redis:7-alpine
#     restart: unless-stopped
#     command: redis-server --save 60 1 --loglevel warning
#     networks: [redis_network]
# networks:
#   redis_network:
#     name: redis_network
docker compose -f redis/docker-compose.yml up -d
# This creates the `redis_network` network.
```

Both networks must exist before starting the app stack.

### Option B — Bundled services

Run Postgres and Redis inside this stack. Add a secret file for the database
password, using the same password as in `secrets/database_url`:

```sh
printf 'YOURPASSWORD' > secrets/postgres_password
```

Then make these changes to `docker-compose.yml`. Under `secrets:`, add:

```yaml
  postgres_password:
    file: ./secrets/postgres_password
```

Under `services:`, add:

```yaml
  postgres:
    image: postgres:18-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: mibudge
      POSTGRES_USER: mibudge
      POSTGRES_PASSWORD_FILE: /run/secrets/postgres_password
      PGDATA: /var/lib/postgresql/data
    secrets:
      - postgres_password
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks: [postgres_net]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U mibudge -d mibudge"]
      interval: 5s
      timeout: 3s
      retries: 5

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    command: redis-server --save 60 1 --loglevel warning
    volumes:
      - redis_data:/data
    networks: [redis_network]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5
```

Give `migrate` a `depends_on` so it waits for both (`web` and the Celery
services already wait for `migrate`):

```yaml
  migrate:
    <<: *base
    restart: "no"
    command: python /app/manage.py migrate --no-input
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
```

Replace the `networks:` section at the bottom with networks this stack owns,
and add the volumes:

```yaml
networks:
  postgres_net:
  redis_network:

volumes:
  postgres_data: {}
  redis_data: {}
```

With bundled services, `secrets/database_url` is
`postgres://mibudge:YOURPASSWORD@postgres:5432/mibudge`, and the Redis
settings in `.env` stay as `dot-env.example` has them
(`redis://redis:6379/0`, `/1` and `/2`).

---

## 4. Start the stack

```sh
docker compose pull
docker compose up -d
```

The `migrate` service runs once on startup and exits; the remaining services
start after it completes successfully.

View logs:

```sh
docker compose logs -f web
docker compose logs -f celeryworker
```

---

## 5. Smoke test

```sh
curl -I https://your-domain/app/login/
# Expect: HTTP/2 200
```

Log in, create a bank account, import a statement, and confirm the celery
worker processes the task (check `docker compose logs celeryworker`).

---

## 6. Updating

Edit `.env` to set the new version, then pull and restart:

```sh
# In .env: VERSION=1.2.3
docker compose pull
docker compose up -d
```

`migrate` runs automatically on every `up`, applying any new migrations before
the web and worker services start.

---

## 7. Rollback

If the release you are leaving has no migrations, edit `.env` to the previous
version, then restart:

```sh
# In .env: VERSION=1.2.2
docker compose up -d
```

The `migrate` service only migrates forward, so a release with migrations
needs them reversed first, while it is still the deployed version:

```sh
# Still on the newer release: migrate each changed app back to its last
# migration in the release you are returning to.
docker compose run --rm migrate python /app/manage.py migrate <app> <migration>
# In .env: VERSION=1.2.2
docker compose up -d
```

Reversing a migration that dropped a column or deleted rows does not bring
that data back, and some migrations cannot be reversed at all; then restore
the database from a backup taken before the upgrade instead. See
[`docs/releasing.md`](../../docs/releasing.md#rolling-back).

---

## 8. SALT_KEY rotation

`SALT_KEY` is used to derive the encryption key for sensitive database fields
(bank account numbers, etc.). To rotate it:

1. Generate a new key:
   ```sh
   python -c "import secrets; print(secrets.token_hex(32), end='')"
   ```

2. Update `secrets/salt_key` to a comma-separated list — new key first:
   ```sh
   printf 'NEW_KEY,OLD_KEY' > secrets/salt_key
   ```
   The first value encrypts all new data; the rest decrypt existing records.

3. Restart the stack: `docker compose up -d`

4. Re-save all records that contain encrypted fields so they are re-encrypted
   with the new key (a Django management command or admin action).

5. Once all records are migrated, remove the old key from `secrets/salt_key`
   and restart again.
