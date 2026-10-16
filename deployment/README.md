# mibudge — Deployment

```
deployment/
  dot-env.dev          # template for a local development .env
  ssl/                 # mkcert TLS certificates, one pair per host (not in git)
  db_backups/          # mounted at /backups in the dev Postgres container
  nginx.conf           # baked into the production image
  supervisord.conf     # baked into the production image
  production/          # everything a production host needs; see its README
```

There are two ways to run mibudge, and each has one `.env`:

| | Local development | Production |
|---|---|---|
| Compose file | `docker-compose.yml` at the repo root (builds the image) | `production/docker-compose.yml` (pulls the image from GHCR) |
| `.env` template | `deployment/dot-env.dev` | `production/dot-env.example` |
| Where `.env` lives | repo root, one per host | next to the compose file on the server |
| Credentials | fixed development values in `.env` | files in `production/secrets/` |
| TLS | the dev server, with an mkcert certificate | your reverse proxy |

---

## Local development

Prerequisites: Docker, [`mkcert`](https://github.com/FiloSottile/mkcert)
(run `mkcert -install` once per machine), `pnpm`, `uv`.

```sh
make up
```

On the first run on a host, `make up`:

1. creates `.env` at the repo root from `deployment/dot-env.dev`, filling in
   this host's name (from `hostname`) as `DEV_HOSTNAME`, `SITE_URL` and
   `ALLOWED_HOSTS`;
2. creates this host's certificate with mkcert, as
   `deployment/ssl/<DEV_HOSTNAME>-ssl_crt.pem` and `-ssl_key.pem`, valid for
   the host name, `localhost`, `127.0.0.1` and `::1`;
3. builds the dev image and starts the stack in the background, then runs the
   Vite dev server in the foreground.

The app is at `https://<DEV_HOSTNAME>:8000`. Mailpit catches outgoing mail
at `http://localhost:8025`, and Flower monitors Celery at
`http://localhost:5555`. Ctrl-C stops Vite; `make down` stops the rest.

`make env` and `make certs` run steps 1 and 2 on their own. `make env`
never overwrites an existing `.env`. `make certs`, which every `make up`
runs, replaces the certificate when it expires within 30 days or this
machine's mkcert CA did not sign it (after reinstalling mkcert, say), and
restarts a running backend so the dev server loads the new one.

### One `.env` for the host and the containers

The root `.env` holds this host's development settings. Two kinds of program
read it:

- Tools run on the host -- `uv run manage.py`, `make test`, `make lint` --
  read it through `app/config/settings.py`. Its service URLs point at the
  ports compose publishes on localhost.
- docker compose loads it into every app container. `x-dev-env` in
  `docker-compose.yml` then overrides the service URLs with the
  docker-internal hostnames and sets the path to this host's certificate.

| Service      | In containers   | From the host    |
|--------------|-----------------|------------------|
| PostgreSQL   | `postgres:5432` | `localhost:6432` |
| Redis        | `redis:6379`    | `localhost:7379` |
| Mailpit SMTP | `mailpit:1025`  | `localhost:1025` |

The database user and password are `debug`/`debug`, and the database is
`mibudge`.

Add any settings of your own, such as importer paths, to the end of `.env`.
`make env` writes `.env` only when it does not exist.

### Several hosts sharing one checkout

The source tree can be shared between machines, for example by a file-sync
service or a network filesystem. Each machine then needs its own settings and
its own certificate:

- **`.env` belongs to one host.** It names that host, and nothing else in the
  stack reads per-host settings. Exclude `.env` from the sync. If it is
  shared, every other host serves the named host's certificate, and
  browsers reject it.
- **`deployment/ssl/` is shared.** Each host's certificate is named after the
  host, so the files sit side by side. Each was signed by the mkcert CA of
  the machine that created it, so each host creates its own with
  `make certs`, and replaces a copy from another machine.

`make up` stops with a message when `.env` has no `DEV_HOSTNAME`. Move the
old file aside, regenerate it, and copy your own settings back:

```sh
mv .env .env.old && make env
```

### Common tasks

```sh
make migrate        # run migrations inside the container
make createadmin    # create the admin / testpass1234 superuser
make test           # run pytest on the host
make lint           # ruff + mypy
make logs           # tail backend and celery logs
make manage_shell   # Django shell_plus inside the container
make purge          # stop the stack and delete its database
```

The importers reach the dev server over TLS by trusting the mkcert root CA:
pass `--trust-local-certs` (see [`docs/importers.md`](../docs/importers.md)).

---

## Production

[`production/README.md`](production/README.md) covers it end to end: secret
files, `.env`, external or bundled Postgres and Redis, starting the stack,
updates, rollback and `SALT_KEY` rotation.

The `web` service listens on `127.0.0.1:${PORT}` (default 8000) and serves
plain HTTP. Put a TLS-terminating reverse proxy, such as Caddy or nginx, in
front of it. The proxy must set `X-Forwarded-Proto`, and
`DJANGO_TRUSTED_PROXY_COUNT` in `.env` must count it.
