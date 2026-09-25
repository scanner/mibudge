# mibudge frontend

The Vue 3 single-page app for mibudge. Django serves it at `/app/*` and
Vue Router handles every sub-route. It talks to the backend only through
the REST API (`/api/v1/`) and the JWT endpoints (`/api/token/...`).

**Architecture, conventions and testing are documented in
[docs/spa/README.md](../docs/spa/README.md).** Start with
[architecture.md](../docs/spa/architecture.md).

## Stack

- Vue 3 (`<script setup>` SFCs), TypeScript in strict mode, Vite
- Pinia for state, Vue Router 4 (history mode, base `/app/`) with typed route names
- Native `fetch`, wrapped once in `src/api/http.ts`
- Types generated from `docs/openapi.yaml` by openapi-typescript
- `decimal.js` for money arithmetic, Tailwind CSS for styling
- Vitest + happy-dom + MSW for tests, oxfmt for formatting (80 columns, `.oxfmtrc.json`), vue-tsc for type checking

## Source layout

```
src/
  main.ts        composition root: Pinia, router, API client, cold-boot session
  domain/        pure TypeScript: money, local dates, RRULE text, budget status, labels
  api/           HTTP transport, errors, generated schema types, one module per resource
  models/        domain types and DTO ↔ model mappers
  stores/        Pinia: session, entity caches, account context, sign-out reset
  composables/   cross-feature behaviour: async state, modals, search, lists, autosave
  features/      per-section logic (use*.ts) and container components
  components/    presentational components: props in, events out
  views/         one route shell per page
  router/        route table, typed names and meta, auth guard
```

`@/` resolves to `src/`. Each layer may import only from the layers
below it; `tests/architecture.test.ts` enforces this.

## Commands

Run these from `frontend/`:

```sh
pnpm install          # install dependencies (pnpm 9)
pnpm dev              # Vite dev server on :5173 (assets only; Django serves /app/)
pnpm build            # type-check + production build → dist/
pnpm type-check       # vue-tsc over src/ and tests/
pnpm fmt              # format src/ and tests/ (pnpm fmt:check in CI)
pnpm test             # run the Vitest suite once (test:watch, test:coverage)
pnpm gen:api-types    # regenerate src/api/schema.d.ts from docs/openapi.yaml
```

For the full stack (Django, Postgres, Redis, Celery), run `make up` from
the repo root. Run `make api-schema` there before `pnpm gen:api-types`
whenever the REST API changes. CI fails when `schema.d.ts` is stale.

## Authentication, in brief

- `/app/login/` posts email and password to `POST /api/token/`. The
  response body carries a short-lived access token, which the session
  store keeps in memory only. The server also sets a long-lived refresh
  token as an httpOnly cookie that JS never reads.
- On cold boot, `main.ts` tries a silent refresh (`POST
  /api/token/refresh/`) before installing the router. A returning user
  skips the login page.
- On a 401, the transport refreshes once (shared by concurrent requests)
  and retries the request. If the refresh fails, the session ends, every
  store is reset, and the user is sent to `/app/login/?next=<page>`.

The details are in [architecture.md](../docs/spa/architecture.md#request-lifecycle).

## Vite and Django

- **`base: '/static/'`** in dev and production. django-vite prefixes
  dev-server asset URLs with `STATIC_URL`, so the Vite dev server serves
  under that path.
- **HTTPS in dev.** The dev server loads the repo's mkcert certificates
  from `deployment/ssl/` when they exist, because the Django dev server
  is HTTPS and browsers block mixed content. Without them, it falls back
  to HTTP, as in CI.
- **`build.manifest: true`** and a fixed `src/main.ts` entry. In
  production, `collectstatic` picks up `dist/`, and django-vite reads
  `manifest.json` to inject the hashed filenames into the
  `spa/shell.html` template.
- **`server.strictPort`** and **`server.cors`** keep port 5173 in sync
  with `DJANGO_VITE_DEV_SERVER_PORT`, and let the Django origin load
  dev assets.

The SPA shell at `/app/` is always rendered by Django, even in
development. The Vite dev server only serves assets and HMR.
