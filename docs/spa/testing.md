# SPA testing

The SPA's tests run under [Vitest](https://vitest.dev/) in a simulated
browser (happy-dom), against a mock REST API built with
[MSW](https://mswjs.io/). No test talks to a real backend: every `fetch`
the SPA makes is answered by a mock handler, and a request to an endpoint
with no handler fails the test.

The harness covers four kinds of test:

- **Unit tests** of pure helpers (`src/utils/`) and single stores.
- **Transport and API tests** that check the exact HTTP requests the SPA
  sends: method, path, query string, headers and body.
- **Auth and token tests** that drive the 401 → refresh → retry cycle.
- **Cross-module tests** that mount a view with the real router, real
  Pinia stores, the real API modules and the transport, with only the
  network mocked.

Tests exercise behaviour through public interfaces (store actions and
state, exported API functions, rendered output and navigation), so that
refactoring the internals does not require rewriting them.

Browser end-to-end testing (Playwright) is out of scope for this harness.

---

## Running the tests

All commands run from `frontend/`:

```sh
pnpm test                       # run every test once
pnpm test:watch                 # re-run affected tests on file changes
pnpm test:coverage              # run once with v8 coverage and thresholds

pnpm test tests/stores/auth.test.ts            # one file
pnpm test tests/stores/                        # one directory
pnpm test -t "shares one refresh"              # tests whose name matches
pnpm test tests/api/client.test.ts -t "ApiError on 404"
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
  tsconfig.vitest.json    # type-checks tests/ (types: vitest, node)
  tests/
    setup.ts              # global setup, the conftest.py analogue
    mocks/
      server.ts           # MSW server + request log
      handlers.ts         # default happy-path handlers for every endpoint
      factories.ts        # make* DTO factories (factory-boy analogue)
    helpers/              # fixtures: withAuth, expire, respondOnce401, mountWithApp
    api/                  # tests for src/api/
    stores/               # tests for src/stores/
    utils/                # tests for src/utils/
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
| fixtures                        | `tests/helpers/` (`withAuth()`, `mountWithApp()`)          |
| `@pytest.mark.parametrize`      | `it.each([...])` / `describe.each([...])`                  |
| freezegun                       | `vi.useFakeTimers()` + `vi.setSystemTime(...)`             |
| `pytest.mark.xfail(strict=True)`| `it.fails(...)`                                            |
| `mocker.patch`                  | `vi.spyOn(...)`, `vi.fn()` (restored after each test)      |

---

## The test environment

`vitest.config.ts` merges `vite.config.ts`, so the `@/` alias and the Vue
plugin are the same as in the app build. It sets:

- `environment: 'happy-dom'` with a page URL of `http://localhost/app/`.
  `src/api/client.ts` fetches relative URLs (`/api/v1/...`); the page URL
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
`fetch` was installed, so the single `fetch()` call in `src/api/client.ts`
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
  level. `src/api/config.ts` reads it at import time, which happens while
  test files load and before any hook runs.
- Starts the MSW server once per file with `onUnhandledRequest: 'error'`.
- Before each test: activates a fresh Pinia (`setActivePinia(createPinia())`)
  and clears `sessionStorage` and `localStorage`.
- After each test: `server.resetHandlers()` drops any `server.use(...)`
  overrides, and the request log is cleared.

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

- `withAuth(token?, user?)` puts the auth store into the logged-in state:
  an access token (default `TEST_TOKEN`) and a user.
- `expire(token?)` makes every `/api/v1/*` request carrying
  `Bearer <token>` get 401, as the backend answers an expired access
  token. Requests with any other token fall through to the normal handler,
  so after a refresh the retry succeeds.
- `respondOnce401(path, method?)` answers only the next request to `path`
  with 401, e.g. `respondOnce401("/api/token/refresh/", "post")` for an
  expired refresh cookie or `respondOnce401("/api/token/", "post")` for bad
  credentials.

```ts
const auth = withAuth();
expire(TEST_TOKEN);
await auth.request("/budgets/");   // 401 → refresh → retry with REFRESHED_TOKEN
```

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

### Pure utilities

Import the function and call it. Prefer `it.each` tables:

```ts
it.each([
  ["RRULE:FREQ=MONTHLY;BYMONTHDAY=1,15", "Every month on the 1st and the 15th"],
  ["RRULE:FREQ=WEEKLY;BYDAY=MO,FR", "Every week on Mo, Fr"],
])("%j → %j", (rule, text) => {
  expect(rruleHuman(rule)).toBe(text);
});
```

### API modules

`tests/api/resources.test.ts` is one `it.each` table with a row per
exported function in `src/api/*.ts` (except `client.ts`). Each row gives
the call, the HTTP method, the path under `/api/v1` including trailing
slash and query string, and the expected JSON body. The test answers that
exact endpoint with a unique payload and checks the function sends the
request as described and returns the payload. The per-resource modules
call `useAuthStore().request()`, so the table runs with `withAuth()`.

### Stores

Setup already activates a fresh Pinia, so call the store directly and
assert on its public state after awaiting its actions:

```ts
withAuth();
server.use(http.get("/api/v1/budgets/", () => HttpResponse.json(makePage([rent]))));
const store = useBudgetsStore();

await store.fetchList({ bank_account: account.id });

expect(store.byId(rent.id)).toEqual(rent);
```

### Composables

Call a composable that uses only reactivity and stores directly inside
the test. A composable that uses lifecycle hooks, `inject`, or the router
must run inside a component: mount a small host component with
`mountWithApp(defineComponent({ setup() { result = useThing(); return () => null; } }))`
and assert on `result`.

### Components

Mount with `mountWithApp(Component, { route, props, pinia })` from
`tests/helpers/mount.ts`. It installs the app's real router (memory history,
so no browser URL changes) and a Pinia, navigates to `route`, mounts, and
flushes pending promises.

To check which store actions a component calls without running them,
pass a testing Pinia; its actions are `vi.fn()` stubs:

```ts
const pinia = createTestingPinia({
  createSpy: vi.fn,
  initialState: { accountContext: { accounts: [account], activeBankAccountId: account.id } },
});
await mountWithApp(TopBar, { route: "/budgets/", pinia });
expect(useBudgetsStore(pinia).fetchOne).toHaveBeenCalledWith(account.unallocated_budget);
```

Use `@pinia/testing` 1.x; 2.x requires Pinia 4.

### Views

Seed the stores the view reads (`withAuth()`, the account context), set up
any `server.use(...)` overrides, then `mountWithApp` and assert on the
rendered output, the request log and the router:

```ts
withAuth();
const ctx = useAccountContextStore();
ctx.accounts = [account];
ctx.setActive(account.id);
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
// WHEN:  each receives 401 and asks the auth store to refresh
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
// Known bug: `formatDateHeader` (src/utils/dates.ts) parses the date
// as browser-local midnight and formats it in the profile zone, so a
// profile zone west of the browser shows the previous day ("Jul 3").
// Convert to `it(...)` when the bug is fixed.
//
it.fails("shows the same date when browser and profile timezones differ", () => {
  expect(formatDateHeader("2026-07-04", "2026-09-24", "America/Los_Angeles")).toBe("Jul 4");
});
```

Current `it.fails` tests:

| Test                                                  | Bug                                                                 |
|-------------------------------------------------------|---------------------------------------------------------------------|
| `tests/utils/dates.test.ts` — `formatDateHeader` with differing timezones | Shows the previous day when the profile zone is west of the browser zone |

---

## Coverage

`pnpm test:coverage` runs v8 coverage over `src/**` and writes an HTML
report to `frontend/coverage/` (gitignored by the root `.gitignore`), plus a
text summary on the console.

Per-directory line thresholds in `vitest.config.ts` fail the run when
coverage drops below them:

| Directory        | Lines |
|------------------|-------|
| `src/api/**`     | 80%   |
| `src/stores/**`  | 80%   |
| `src/utils/**`   | 80%   |

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
A failing test or an unmet coverage threshold fails the pipeline.

Every Drone step installs `pnpm@9`, matching `Dockerfile`, the lockfile
format (`lockfileVersion: '9.0'`), and `packageManager` in
`frontend/package.json`. Use pnpm 9 locally too; a different major
rewrites `pnpm-lock.yaml`, and CI's `--frozen-lockfile` install fails on a
stale lockfile. After `pnpm add`, commit the updated `pnpm-lock.yaml`.

---

## Checklist: which tests do I add?

**A new API function in `src/api/*.ts`**

- [ ] Add a default handler for its endpoint to `tests/mocks/handlers.ts`
      if none exists (shape from `docs/openapi.yaml`).
- [ ] Add one row to `tests/api/resources.test.ts`: call, method, path
      with query string, JSON body.
- [ ] Add a factory to `tests/mocks/factories.ts` if it returns a new DTO.

**A new or changed store in `src/stores/`**

- [ ] `tests/stores/<store>.test.ts`: each action's effect on public state,
      the requests it sends (request log), and its error path.
- [ ] If it persists anything (sessionStorage, localStorage), a test that
      reads and writes storage.

**A new view in `src/views/`**

- [ ] `tests/views/<View>.test.ts` with `mountWithApp`: rendered data comes
      from the mock response, the error state appears on a failing
      endpoint, and any navigation it triggers lands.
- [ ] If it adds a route, a `tests/router/guards.test.ts` row for whether
      it is public or protected.

**A new component in `src/components/`**

- [ ] `tests/components/<Component>.test.ts` for props → rendered output
      and emitted events; use `createTestingPinia` to check store actions
      it calls.

**A new pure helper in `src/utils/`**

- [ ] An `it.each` table in `tests/utils/<module>.test.ts`, including edge
      cases (empty input, month/year boundaries, timezones).

**A bug you found but are not fixing**

- [ ] An `it.fails` test asserting the correct behaviour, with a comment
      naming the bug, and a row in the `it.fails` table above.
