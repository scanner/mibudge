# mibudge frontend

Vue 3 SPA for the mibudge personal budgeting service. Served by Django at
`/app/*`; all sub-routes are handled client-side by Vue Router.

## Stack

- **Vue 3** with `<script setup>` SFCs throughout
- **TypeScript** — strict mode, no `any` shortcuts
- **Vite** for dev server (HMR) and production builds
- **Pinia** for state management
- **Vue Router** in history mode, base `/app/`
- Native `fetch` — no axios or other HTTP client

## Source layout

```
src/
  main.ts          # Entry point — wires up Pinia, Router, auth init, then mounts
  App.vue          # Root component: <RouterView /> only
  style.css        # Minimal global reset
  api/
    client.ts      # Base fetch wrapper: apiFetch<T>, ApiError, AuthError
  stores/
    auth.ts        # Pinia auth store: access token, refresh flow, authenticated requests
  router/
    index.ts       # Route definitions (history mode, base /app/)
  views/           # One component per route
    HomeView.vue   # Placeholder — will become the budget dashboard
```

The `@` alias resolves to `src/`, so imports look like `@/stores/auth` rather
than `../../stores/auth`.

## Authentication

Authentication is a two-token JWT scheme managed entirely between Django and
this SPA. No session cookies, no localStorage — the access token lives in
JS memory only.

### Login flow

Login happens outside the SPA entirely — Django's allauth handles credentials
at `/accounts/login/`. After a successful login:

1. Django's `SpaLoginView` issues a JWT pair and sets the **refresh token** as
   an `httpOnly; Secure; SameSite=Strict` cookie (never readable by JS).
2. It renders a minimal handoff page (`spa/token_handoff.html`) that sets
   `window.__INITIAL_TOKEN__` to the access token and immediately redirects
   to `/app/`.
3. `main.ts` calls `useAuthStore().init()` before mounting. `init()` reads
   `window.__INITIAL_TOKEN__` into the Pinia store and deletes it from
   `window` so it is not readable after that single read.
4. The app mounts with the token already in state; the first render is
   authenticated.

### Access token

- Held in a `ref<string | null>` inside `stores/auth.ts` — never written to
  `localStorage` or any cookie JS can read.
- Lifetime: 60 minutes.
- Attached to API requests as `Authorization: Bearer <token>` by `apiFetch`.

### Silent refresh

When the access token expires, the auth store handles it transparently:

1. `apiFetch` throws `ApiError` with `status === 401`.
2. `authStore.request()` catches the 401 and calls `authStore.refresh()`.
3. `refresh()` posts to `/api/token/refresh/` — the browser automatically
   sends the httpOnly refresh cookie; the response returns a new access token
   and rotates the cookie.
4. The original request is retried once with the new token.
5. If the refresh also fails (cookie expired or revoked), an `AuthError` is
   thrown and the session is gone — the user must log in again.

The refresh token has a 14-day sliding window: each successful refresh resets
the clock. More than 14 days of inactivity requires re-login.

### Making authenticated requests

Components and stores should use `authStore.request<T>(url, options)`, not
`apiFetch` directly. `request` handles token injection and the 401 → refresh
→ retry cycle automatically:

```ts
const data = await authStore.request<BudgetList>('/budgets/')
```

`apiFetch` is a lower-level primitive used only by the auth store itself (for
the unauthenticated refresh call) and in tests.

## API client (`src/api/client.ts`)

`apiFetch<T>(url, token, options)` is a thin wrapper around the browser's
native `fetch`:

- Prefixes all URLs with `/api` — call `apiFetch('/budgets/', ...)`, not the
  full path.
- Sets `Content-Type: application/json` on every request.
- Adds `Authorization: Bearer <token>` only when a token is provided — the
  refresh endpoint must not receive a stale token.
- Throws `ApiError(status, body)` for any non-2xx response.
- Returns `null` for `204 No Content` rather than trying to parse an empty body.
- Does **not** handle 401 retry — that is intentionally in the auth store so
  token storage and retry logic are co-located.

## Vite configuration

`vite.config.ts` has a few mibudge-specific settings worth knowing:

- **`base`**: `'/static/'` in production so asset URLs match Django's
  `STATIC_URL`. In dev mode the base is unused — `django-vite` points
  `<script>` tags directly at the Vite dev server.
- **`build.manifest: true`**: required by `django-vite` to resolve
  content-hashed filenames at render time.
- **`build.rollupOptions.input`**: explicitly set to `/src/main.ts` so the
  manifest always records the entry under a stable key.
- **`server.strictPort: true`**: fails fast if port 5173 is taken rather than
  silently switching, keeping `DJANGO_VITE_DEV_SERVER_PORT` in sync.
- **`server.cors: true`**: allows the Django dev server (a different origin)
  to load assets from the Vite dev server.

## Development

```bash
pnpm install        # Install dependencies
pnpm dev            # Start Vite dev server on port 5173 (HMR enabled)
pnpm build          # Production build → dist/
pnpm type-check     # Run vue-tsc
```

For the full dev stack (Django + Postgres + Redis + Celery), run `make up`
from the repo root. Django will proxy asset requests to the Vite dev server
when `DEBUG=True` (the default for local dev).

The Vite dev server does not serve the app directly — it only serves assets.
The SPA shell at `/app/` is always rendered by Django, even in development.

## Django integration

In production, `pnpm build` writes `dist/` which Django's `collectstatic`
picks up. The `manifest.json` in `dist/` tells `django-vite` which
content-hashed filenames to inject into the `spa/shell.html` template.

In development, `django-vite` replaces the manifest-based tags with direct
references to the Vite dev server (`http://localhost:5173/src/main.ts`),
enabling HMR without a production build step.
