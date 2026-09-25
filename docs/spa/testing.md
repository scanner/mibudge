# SPA testing

The SPA's tests run under [Vitest](https://vitest.dev/) in a simulated
browser (happy-dom), against a mock REST API built with
[MSW](https://mswjs.io/). No test talks to a real backend: every `fetch`
the SPA makes is answered by a mock handler, and a request to an endpoint
with no handler fails the test.

The harness covers four kinds of test:

- **Unit tests** of the pure layers (`src/domain/`, `src/models/`), the
  shared composables (`src/composables/`) and single stores.
- **Transport and API tests** that check the exact HTTP requests the SPA
  sends: method, path, query string, headers and body.
- **Auth and token tests** that drive the 401 → refresh → retry cycle.
- **Cross-module tests** that mount a view with the real router, real
  Pinia stores, the real API modules and the transport, with only the
  network mocked.

Tests exercise behaviour through public interfaces (store actions and
state, exported API functions, rendered output and navigation), so that
refactoring the internals does not require rewriting them.

An **architecture test** (`tests/architecture.test.ts`) checks the
layering rules of [architecture.md](architecture.md) on every run.

Browser end-to-end testing (Playwright) is out of scope for this harness.

---

## Running the tests

All commands run from `frontend/`:

```sh
pnpm test                       # run every test once
pnpm test:watch                 # re-run affected tests on file changes
pnpm test:coverage              # run once with v8 coverage and thresholds

pnpm test tests/stores/session.test.ts         # one file
pnpm test tests/stores/                        # one directory
pnpm test -t "shares one refresh"              # tests whose name matches
pnpm test tests/api/http.test.ts -t "401 handling"
```

From the repo root, `make test-frontend` runs `pnpm test`.

`pnpm type-check` (`vue-tsc -b`) type-checks the tests as well as `src/`,
through `tsconfig.vitest.json`. `pnpm fmt` / `pnpm fmt:check` format
`src/` and `tests/`.

---

## Layout and naming

```
frontend/
  vitest.config.ts        # merges vite.config.ts; environment, setup, coverage
  tsconfig.vitest.json    # type-checks tests/ (types: vitest, node, vite/client)
  tests/
    setup.ts              # global setup, the conftest.py analogue
    architecture.test.ts  # layering rules over every src/ import
    mocks/
      server.ts           # MSW server + request log
      handlers.ts         # default happy-path handlers for every endpoint
      factories.ts        # make* DTO factories (factory-boy analogue)
    helpers/              # fixtures, re-exported from helpers/index.ts:
                          #   withAuth, expire, respondOnce401 (auth.ts)
                          #   withAccounts (accounts.ts)
                          #   mountWithApp (mount.ts), withSetup (withSetup.ts)
    domain/               # tests for src/domain/
    api/                  # tests for src/api/
    models/               # tests for src/models/
    stores/               # tests for src/stores/
    composables/          # tests for src/composables/
    features/             # tests for src/features/
    components/           # tests for src/components/
    views/                # tests for src/views/
    router/               # tests for src/router/
```

`tests/` mirrors `src/`, the same convention as `app/tests/` mirroring
`app/`. A test for `src/stores/budgets.ts` is `tests/stores/budgets.test.ts`;
a test for `src/views/LoginView.vue` is `tests/views/LoginView.test.ts`.
Only files named `*.test.ts` are collected.

Test APIs are imported explicitly (`import { describe, expect, it } from
"vitest"`); Vitest globals are not enabled.

### pytest analogues

| pytest                          | Here                                                       |
|---------------------------------|------------------------------------------------------------|
| `conftest.py`                   | `tests/setup.ts` (runs before every test file)             |
| factory-boy factories           | `tests/mocks/factories.ts` (`makeBudget({...})`)           |
| fixtures                        | `tests/helpers/` (`withAuth()`, `withAccounts()`, `mountWithApp()`, `withSetup()`) |
| `@pytest.mark.parametrize`      | `it.each([...])` / `describe.each([...])`                  |
| freezegun                       | `vi.useFakeTimers()` + `vi.setSystemTime(...)`             |
| `pytest.mark.xfail(strict=True)`| `it.fails(...)`                                            |
| `mocker.patch`                  | `vi.spyOn(...)`, `vi.fn()` (restored after each test)      |

---

## The test environment

`vitest.config.ts` merges `vite.config.ts`, so the `@/` alias and the Vue
plugin are the same as in the app build. It sets:

- `environment: 'happy-dom'` with a page URL of `http://localhost/app/`.
  `src/api/http.ts` fetches relative URLs (`/api/v1/...`); the page URL
  gives them an origin to resolve against, as the Django-served shell does
  in the browser.
- `setupFiles: ['tests/setup.ts']`, `include: ['tests/**/*.test.ts']`.
- `restoreMocks: true` and `unstubEnvs: true`, so spies and `vi.stubEnv()`
  values are undone after every test.
- `env: { TZ: 'America/New_York', LC_ALL: 'en_US.UTF-8' }`, so local-time
  arithmetic and `toLocaleDateString(undefined, ...)` output are the same
  on every machine (see [Time and timezones](#time-and-timezones)).

`vite.config.ts` loads its mkcert certificates from `deployment/ssl/` only
when they exist and otherwise leaves the dev server on plain HTTP, so the
config loads under Vitest in CI, where the certificates are absent.

### Why happy-dom, and how `fetch` reaches MSW

The environment is happy-dom (not jsdom). Vitest's happy-dom environment
installs happy-dom's `fetch`, `Request`, `Response`, `Headers` and
`FormData` as globals. MSW's `setupServer().listen()` (from `msw/node`)
then replaces `globalThis.fetch` with an interceptor that wraps whatever
`fetch` was installed, so the single `fetch()` call in `src/api/http.ts`
reaches the mock handlers. This was verified with a throwaway test before
the harness was built; no delegation to Node's `fetch` is needed.

Two happy-dom behaviours the harness accounts for:

- `Headers` keeps the header-name case the caller used. The request log
  lower-cases names, as the Fetch spec does, so tests read
  `headers.authorization`.
- A `FormData` body is serialized with a `multipart/form-data; boundary=...`
  content type set by happy-dom, as a browser would, so the transport's
  "don't set `Content-Type` for `FormData`" behaviour is observable.

### What `tests/setup.ts` does

- Sets `window.__mibudge = { adminEmail: 'admin@example.com' }` at module
  level, as the Django shell template does in production
  (`useShellConfig()` reads it).
- Starts the MSW server once per file with `onUnhandledRequest: 'error'`.
- Before each test:
  - Creates a fresh Pinia with `resetPlugin`, as `main.ts` does.
  - Installs it in a bare `createApp({})`, because Pinia applies plugins
    only once it is installed in an app.
  - Makes it the active Pinia.
  - Calls `initApi(createSessionHttpClient())`, so the `api` registry
    uses that Pinia's session store for tokens and refresh.
  - Clears `sessionStorage` and `localStorage`.
- After each test:
  - `enableAutoUnmount(afterEach)` unmounts every mounted component, so
    modal scroll locks and window listeners don't leak.
  - `server.resetHandlers()` drops any `server.use(...)` overrides.
  - The request log is cleared.

---

## The mock REST API

### Default handlers

`tests/mocks/handlers.ts` has a happy-path handler for every endpoint the
SPA calls, with paths and shapes from `docs/openapi.yaml` (list them with
`grep -n '^  /api' docs/openapi.yaml`). List endpoints return DRF's
`{count, next, previous, results}` envelope with one factory-built item;
detail endpoints echo the requested id; `PATCH`/`POST` handlers echo the
submitted fields. `POST /api/token/` returns `LOGIN_TOKEN` and
`POST /api/token/refresh/` returns `REFRESHED_TOKEN`.

The defaults do not check the `Authorization` header; a test that needs a
401 installs one (below).

### Factories

`tests/mocks/factories.ts` builds schema-valid DTOs with overridable
fields: `makeUser`, `makeBank`, `makeBankAccount`, `makeBudget`,
`makeTransaction`, `makeAllocation`, `makeInternalTransaction`,
`makeFundingSummary`, `makeApiKey`, `makeInvitation`,
`makeNotificationPreference`, `makeChannelPreference`, and `makePage(results)`
for the pagination envelope. Money values are decimal strings (`"12.34"`),
as the API sends them. Ids come from a sequence, so every object is
distinct.

```ts
const account = makeBankAccount({ name: "Household" });
const rent = makeBudget({ name: "Rent", budget_type: "R", bank_account: account.id });
const page = makePage([rent], { next: "http://localhost/api/v1/budgets/?page=2" });
```

### Per-test overrides

`server.use(...)` prepends handlers for the current test only:

```ts
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";

server.use(
  http.get("/api/v1/budgets/", () => HttpResponse.json(makePage([rent]))),
  http.get("/api/v1/bank-accounts/:id/funding-summary/", () =>
    new HttpResponse(null, { status: 500 }),
  ),
);
```

Pass `{ once: true }` as the third argument of `http.get(...)` for a
handler that answers only the next matching request.

### Simulating 401 and token expiry

`tests/helpers/auth.ts`:

- `withAuth(token?, user?)` puts the session store into the logged-in
  state: an access token (default `TEST_TOKEN`) and a user (a `UserDto`,
  default `makeUser()`, mapped to the model).
- `expire(token?)` makes every `/api/v1/*` request carrying
  `Bearer <token>` get 401, as the backend answers an expired access
  token. Requests with any other token fall through to the normal handler,
  so after a refresh the retry succeeds.
- `respondOnce401(path, method?)` answers only the next request to `path`
  with 401, e.g. `respondOnce401("/api/token/refresh/", "post")` for an
  expired refresh cookie or `respondOnce401("/api/token/", "post")` for bad
  credentials.

```ts
withAuth();
expire(TEST_TOKEN);
await api.budgets.list();   // 401 → refresh → retry with REFRESHED_TOKEN
```

`tests/helpers/accounts.ts`:

- `withAccounts(dtos, activeId?)` seeds the bank-accounts cache with the
  given `BankAccountDto`s and makes the first (or `activeId`) the active
  account, without going through the API. It returns the
  account-context store.

### Asserting on the request log

`tests/mocks/server.ts` records every intercepted request, in order, as
`{method, url, path, headers, body}` (`path` is pathname + query string;
header names are lower-case; `body` is parsed JSON, field → value for
multipart with a `File` recorded as its name, or `undefined`). The query
helpers are async because body parsing is:

```ts
import { lastRequest, requestLog, requestsTo } from "../mocks/server";

expect(await requestsTo("POST", "/api/token/refresh/")).toHaveLength(1);

const req = await lastRequest();
expect(req?.path).toBe("/api/v1/budgets/?bank_account=abc&archived=false");
expect(req?.headers.authorization).toBe(`Bearer ${TEST_TOKEN}`);
expect(req?.body).toEqual({ name: "Rent" });
```

`requestsTo` matches the pathname exactly and ignores the query string.

---

## Testing each layer

### Domain and models

`src/domain/` and `src/models/` are pure, so import the function and
call it. Prefer `it.each` tables:

```ts
it.each([
  ["RRULE:FREQ=MONTHLY;BYMONTHDAY=1,15", "Every month on the 1st and the 15th"],
  ["RRULE:FREQ=WEEKLY;BYDAY=MO,FR", "Every week on Mo, Fr"],
])("%j → %j", (rule, text) => {
  expect(rruleHuman(rule)).toBe(text);
});
```

Model tests (`tests/models/`) build a DTO with a factory, map it, and
assert on the model. They also run the reverse mapping for request
bodies, including the null, empty-string and default cases:

```ts
const budget = budgetFromDto(makeBudget({ balance: "12.50", target_date: "" }));
expect(budget.balance.equals(Money.of("12.50"))).toBe(true);
expect(budget.targetDate).toBeNull();
```

### API modules

`tests/api/http.test.ts` covers the transport (`createHttpClient`):
paths, headers, bodies and query strings, pagination, empty responses,
DRF error parsing, and the 401 → refresh → retry cycle. It builds its own
client with a stub `refresh`. Its "session-wired client" block runs the
same cycle through `createSessionHttpClient()` and the session store.

`tests/api/resources.test.ts` is one `it.each` table with a row per
endpoint function in `src/api/resources/*.ts`, called through the `api`
registry (`api.budgets.list(...)`). Each row gives:

- the call;
- the HTTP method;
- the path under `/api/v1`, with trailing slash and query string;
- the expected JSON body.

The test answers that exact endpoint with a unique payload. It checks
that the function sends the request as described and returns the
payload. `api` is bound to the session-wired client in `tests/setup.ts`,
and the table runs with `withAuth()`.

### Stores

Setup already activates a fresh Pinia, so call the store directly and
assert on its public state after awaiting its actions:

```ts
withAuth();
server.use(http.get("/api/v1/budgets/", () => HttpResponse.json(makePage([rent]))));
const store = useBudgetsStore();

await store.fetchList({ bank_account: account.id });

expect(store.byId(rent.id)?.name).toBe("Rent");   // cached as a model
```

### Composables

Call a composable that uses only reactivity directly inside the test.
A composable that registers lifecycle hooks or `onScopeDispose` (for
example `useModal`, `useInfiniteList` or `useFindShortcut`) must run
inside a component. Use `withSetup` from `tests/helpers`:

```ts
const { result, wrapper } = withSetup(() => useModal(() => open.value, onClose));
// ...
wrapper.unmount();   // runs the composable's cleanup
```

A feature composable that needs the router uses `mountWithApp` with a
small host component instead, or is tested through its view.

### Components

Mount with `mountWithApp(Component, { route, props, pinia })` from
`tests/helpers/mount.ts`. It installs the app's real router (memory history,
so no browser URL changes) and a Pinia, navigates to `route`, mounts, and
flushes pending promises.

A presentational component (`src/components/`) needs no router, store
or mock API. Mount it with `mount(Component, { props })` and assert on
the output and `wrapper.emitted()`.

To check which store actions a container calls, pass a testing Pinia
with `stubActions: false`. In a setup store every returned function is
an action, including lookups like `bankAccounts.byId`. With stubbed
actions those would return `undefined`, so here actions are spied on
and still run:

```ts
const pinia = createTestingPinia({
  createSpy: vi.fn,
  stubActions: false,
  initialState: {
    session: { accessToken: "t" },
    bankAccounts: { accounts: [bankAccountFromDto(account)], loaded: true },
    accountContext: { activeBankAccountId: account.id },
  },
});
await mountWithApp(AppShell, { route: "/budgets/", pinia });
expect(useBudgetsStore(pinia).fetchOne).toHaveBeenCalledWith(account.unallocated_budget);
```

`initialState` is keyed by each store's returned state refs:
`bankAccounts.accounts`, `budgets.cache`, `allocations.byAccount`.

Use `@pinia/testing` 1.x; 2.x requires Pinia 4.

### Views

Seed the stores the view reads (`withAuth()`, `withAccounts()`), set up
any `server.use(...)` overrides, then `mountWithApp` and assert on the
rendered output, the request log and the router:

```ts
withAuth();
withAccounts([account]);
server.use(http.get("/api/v1/budgets/", () => new HttpResponse(null, { status: 500 })));

const { wrapper } = await mountWithApp(BudgetsView, { route: "/budgets/" });

expect(wrapper.text()).toContain("HTTP 500");
```

Route components are lazy-loaded. When a view navigates without awaiting
the navigation (for example `LoginView` calls `router.replace()` after
login), wait for it with
`await vi.waitFor(() => expect(router.currentRoute.value.path).toBe("/"))`.

### Router

`createAppRouter(createMemoryHistory("/app/"))` from `src/router` builds a
router with the app's routes and auth guard; push a path and read
`router.currentRoute.value`.

---

## Time and timezones

The suite runs with `TZ=America/New_York` and `LC_ALL=en_US.UTF-8`
(`env` in `vitest.config.ts`, passed to the worker process), so "local
time" is Eastern and default-locale date formatting is US English.

Freeze the clock with fake timers:

```ts
afterEach(() => vi.useRealTimers());

it("...", () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-09-24T03:30:00Z"));
  expect(todayDateStr("America/Los_Angeles")).toBe("2026-09-23");
});
```

Fake timers also replace `setTimeout`; with MSW or pending promises, use
`vi.useFakeTimers({ toFake: ["Date"] })` to freeze only the clock.

To run a single test in another browser timezone, stub `TZ`; Node applies
a `TZ` change immediately, and `unstubEnvs` restores New York afterwards:

```ts
it("in Asia/Tokyo", () => {
  vi.stubEnv("TZ", "Asia/Tokyo");
  expect(parseLocalDate("2026-08-01").getDate()).toBe(1);
});
```

The profile timezone (`user.timezone`) is a separate input: pass it to the
date helpers, or set it with `withAuth(TEST_TOKEN, makeUser({ timezone }))`.

---

## Conventions

### Gherkin comment block

Every test has a Gherkin comment block directly above its `it(...)`. It
describes what the **production code** guarantees, not what the test does:

```ts
// GIVEN: three requests in flight whose access token has expired
// WHEN:  each receives 401 and the transport refreshes the token
// THEN:  exactly one refresh is sent to the server
//  AND:  every original request is retried with the new token and resolves
//
it("shares one refresh across concurrent 401s", async () => { ... });
```

Test mechanics (MSW overrides, fake timers, why a value was chosen) go in
ordinary comments next to the code that sets them up, never in the
Gherkin. A table-driven `it.each` has one block describing the rule the
table exercises.

### Comments

- A comment names the mechanism, then says what it achieves.
- A multi-line comment block ends with a line containing only `//`,
  directly above the code it describes.
- Inline code in comments uses single backticks.
- Test files open with the same file-header comment style as `src/`.

### Known bugs: `it.fails`

A known bug is recorded as an `it.fails(...)` test that asserts the
**correct** behaviour, with a comment naming the bug. The test passes
while the bug exists and fails once the bug is fixed, which prompts the
fixing change to convert it to a plain `it(...)`:

```ts
// Known bug: `formatThing` (src/domain/thing.ts) drops the last
// character of a two-word name ("Grocerie").
// Convert to `it(...)` when the bug is fixed.
//
it.fails("keeps the whole name", () => {
  expect(formatThing("Weekly Groceries")).toBe("Weekly Groceries");
});
```

Current `it.fails` tests:

| Test | Bug |
|------|-----|
| —    | None. The last one (`formatDateHeader` showing the previous day when the browser zone differed from the profile zone) was fixed and is now a plain `it.each` over browser zones in `tests/domain/dates.test.ts`. |

---

## Coverage

`pnpm test:coverage` runs v8 coverage over `src/**` and writes an HTML
report to `frontend/coverage/` (gitignored by the root `.gitignore`), plus a
text summary on the console.

Per-directory line thresholds in `vitest.config.ts` fail the run when
coverage drops below them:

| Directory             | Lines |
|-----------------------|-------|
| `src/api/**`          | 80%   |
| `src/composables/**`  | 80%   |
| `src/domain/**`       | 80%   |
| `src/models/**`       | 80%   |
| `src/stores/**`       | 80%   |

`src/api/schema.d.ts` is a type declaration file and has no runtime
code to cover.

Views and components have no threshold yet. To raise a threshold or add
one, edit `coverage.thresholds` in `vitest.config.ts`, for example
`'src/components/**': { lines: 60 }`, and check `pnpm test:coverage` still
passes. Raise thresholds as coverage grows so they keep guarding it.

---

## CI

The Drone `mibudge Tests` pipeline has a `frontend tests` step that runs
`pnpm test:coverage` in `node:22`. It depends on `frontend lint`, which
runs `pnpm install --frozen-lockfile` into the shared
`frontend-node-modules` volume, and runs in parallel with `frontend build`.
A failing test, an unmet coverage threshold, or a layering violation
caught by the architecture test fails the pipeline.

The `frontend lint` step also checks that the generated API types are
current: `pnpm gen:api-types && git diff --exit-code src/api/schema.d.ts`.
After changing the REST API, run `make api-schema` and
`pnpm gen:api-types`, and commit both files (see
[api-and-models.md](api-and-models.md#generated-types-apischemadts)).

### The architecture test

`tests/architecture.test.ts` reads the import statements of every file
under `src/`: static, side-effect, dynamic and re-export imports,
including SFC `<script>` blocks. It resolves relative imports to `@/...`
and checks each layer's forbidden imports (see
[architecture.md](architecture.md#layers)). It also checks that
`api/http.ts` is the only file that calls `fetch(`.

A violation fails with the file and the import:

```
× components/ are presentational
  - Expected: []
  + Received: ["components/shared/EmptyState.vue imports @/api"]
```

Fix it by moving the call up a layer, not by adding an exception. The
rule table's `allowed` list is for type-only or error-helper modules
(`@/api/dto` for models, `@/api/errors` for composables).

Every Drone step installs `pnpm@9`, matching `Dockerfile`, the lockfile
format (`lockfileVersion: '9.0'`), and `packageManager` in
`frontend/package.json`. Use pnpm 9 locally too; a different major
rewrites `pnpm-lock.yaml`, and CI's `--frozen-lockfile` install fails on a
stale lockfile. After `pnpm add`, commit the updated `pnpm-lock.yaml`.

---

## Checklist: which tests do I add?

**A new API function in `src/api/resources/*.ts`**

- [ ] Add a default handler for its endpoint to `tests/mocks/handlers.ts`
      if none exists (shape from `docs/openapi.yaml`).
- [ ] Add one row to `tests/api/resources.test.ts`: call, method, path
      with query string, JSON body.
- [ ] Add a factory to `tests/mocks/factories.ts` if it returns a new DTO.

**A new or changed model in `src/models/`**

- [ ] An `it.each` table in `tests/models/<model>.test.ts` (or a block in
      `tests/models/resources.test.ts` for small models) for `*FromDto`
      and any `*To*Dto`: nulls, empty strings, defaults, money and dates.

**A new or changed store in `src/stores/`**

- [ ] `tests/stores/<store>.test.ts`: each action's effect on public state,
      the requests it sends (request log), and its error path.
- [ ] If it persists anything (sessionStorage, localStorage), a test that
      reads and writes storage.
- [ ] A new store defines `reset()`. Add its seeded state to the sign-out
      test in `tests/stores/reset.test.ts`.

**A new composable in `src/composables/`**

- [ ] `tests/composables/<name>.test.ts`, using `withSetup` if it
      registers lifecycle hooks: its state transitions, cleanup on
      unmount, and the stale-response or race case if it loads data.

**A new feature composable or component in `src/features/`**

- [ ] Tests through its view (`tests/views/`) or directly in
      `tests/features/<section>/`: the requests it sends, the store
      updates it makes, and its error message.

**A new view in `src/views/`**

- [ ] `tests/views/<View>.test.ts` with `mountWithApp`: rendered data comes
      from the mock response, the error state appears on a failing
      endpoint, and any navigation it triggers lands.
- [ ] If it adds a route, a `tests/router/guards.test.ts` row for whether
      it is public or protected.

**A new component in `src/components/`**

- [ ] `tests/components/<Component>.test.ts` for props → rendered output
      and emitted events.

**A new pure helper in `src/domain/`**

- [ ] An `it.each` table in `tests/domain/<module>.test.ts`, including edge
      cases (empty input, month/year boundaries, timezones).

**A bug you found but are not fixing**

- [ ] An `it.fails` test asserting the correct behaviour, with a comment
      naming the bug, and a row in the `it.fails` table above.
