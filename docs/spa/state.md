# SPA state

Where state lives in the SPA, how the Pinia stores cache server data and
keep it current, and what happens on sign-out. The stores are in
`frontend/src/stores/`; see [architecture.md](architecture.md) for how
they fit with the other layers.

---

## The stores

All stores are setup stores (`defineStore(id, () => { ... })`). Each
holds models from `models/`, never DTOs, and defines `reset()`.

| Store (`use…Store`) | File                       | Responsibility                                                                                                                                    |
|---------------------|----------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------|
| `session`           | `stores/session.ts`        | The in-memory access token, the signed-in `user`, `isAuthenticated` and the profile `timezone`. Sign-in (`login`), token renewal (`renewToken`, `refresh`), `loadUser`, `updateProfile`, `logout`. Also builds the session-wired HTTP client (`createSessionHttpClient`). |
| `bankAccounts`      | `stores/bankAccounts.ts`   | The user's bank accounts, in list order. `loadAll`, `refresh`, `invalidate`, `fetchOne`, `create`, `update`, `remove`; read with `all` and `byId`. |
| `accountContext`    | `stores/accountContext.ts` | Which account the user is looking at: `activeBankAccountId`, `activeBankAccount`, `unallocatedBudgetId`. `init()` picks the account: the one stored for this tab, else the user's default, else the first. `refresh()` moves off a deleted account. The choice persists per tab in `sessionStorage`. |
| `budgets`           | `stores/budgets.ts`        | Budgets keyed by id. `fetchOne`, `fetchList` (every page), `refreshAccount`, `create`, `update`, `archive`, `transfer`; read with `byId`, `forAccount`, `names`. |
| `allocations`       | `stores/allocations.ts`    | Every allocation of an account, indexed by transaction id. `loadForAccount` (once per account, concurrent callers share one fetch), `setForTransaction`, `invalidate`. |
| `transactionNav`    | `stores/transactionNav.ts` | The ids of the rows the transaction list last showed, so the detail page can step to the previous or next row. It also keeps the list's search and filter across a visit to the detail page. |

`stores/reset.ts` is not a store. It holds the reset plugin (below).

---

## Caching and invalidation

The entity caches (`bankAccounts`, `budgets`, `allocations`) follow the
same rules:

- **Readers read from the cache.** Views and features use `byId`,
  `forAccount`, `all` and `indexFor`, all computed from the cached
  models. A feature that loads data (`useBudgetDetail`, `useOverview`)
  calls the store's fetch action and then reads the result back through
  `byId`, not from the fetch's return value. That way a later update by
  anyone shows up on its page.
- **Mutations go through the store.** `create`, `update`, `archive`,
  `transfer` and `remove` send the request, map the server's answer and
  write it into the cache. Callers never copy a result back by hand.
- **Server-side side effects are refetched.** Some operations move money
  between budgets on the server:
  - archiving a budget (its balance goes to Unallocated);
  - saving a split;
  - a funding run;
  - a transfer.

  After one of these, the caller refetches what changed:
  `budgets.refreshAccount(accountId)` for an account's budgets, or
  `fetchOne` for the two ends of a transfer. A split also calls
  `allocations.setForTransaction(...)`, so the transaction list needs no
  full refetch.
- **`invalidate` marks data stale without fetching.** The next read
  refetches:
  - `bankAccounts.invalidate()`: the next `loadAll()` refetches.
  - `budgets.invalidate(ids?)`: drops the given entries, or all of them.
  - `allocations.invalidate(accountId?)`: drops that account's index,
    or all of them. A load already in flight when you invalidate will
    not write its now-stale result.

  Use it when you know data changed but nothing is on screen to refetch
  it now.
- **Loads are guarded against stale responses.** Anything keyed on the
  active account or a route param loads through `useResource` /
  `useAsync` (see [composables](#store-vs-composable-vs-local-state)).
  Those drop a response that arrives after the key has changed, so
  switching accounts quickly never shows the previous account's data.

A store does not hold loading or error state for a single page. The
budgets store's `loading` / `error` describe its last list fetch;
per-page state comes from `useResource` in the feature composable.

---

## Sign-out resets every store

`main.ts` and `tests/setup.ts` install `resetPlugin` from
`stores/reset.ts` on the Pinia. The plugin records each store as it is
created. `resetAllStores(pinia)` then calls every recorded store's
`reset()`.

`session.logout()` calls `resetAllStores`. It runs on:

- **Sign-out.** `features/auth/useSignOut.ts` calls `logout()`, then
  navigates to the login page.
- **Session end.** When a token refresh fails, the session-wired HTTP
  client calls `logout()` before `main.ts`'s `onAuthFailure` redirects
  to `/app/login/?next=<path>`.

After a reset no cached account, budget, allocation, navigation list or
stored active-account id survives into the next user's session in the
same tab.

**Every store must define `reset()`** that returns all of its state to
the initial values (and clears anything it persisted).
`tests/stores/reset.test.ts` globs `src/stores/*.ts` and fails if any
store has no `reset`. It also seeds every store, signs out, and checks
that every store is empty and the tab's stored account is gone. When you
add a store, add its state to that sign-out test.

The refresh cookie stays valid after sign-out until it expires. There is
no server-side logout endpoint yet.

---

## Store vs composable vs local state

| Put it in…                                 | When                                                                                                                                    | Examples                                                                    |
|--------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------|
| **A store** (`stores/`)                    | More than one route or section reads it, it must outlive the page, or one section must see another's change.                           | The session, the active account, the budget cache the top bar and budget pages share, the transaction list's row order for the detail page's prev/next. |
| **A feature composable** (`features/<section>/use*.ts`) | Data and actions belonging to one section. It loads through `api` or a store, holds the section's form state, and exposes computed views of it. | `useBudgetDetail`, `useMoveMoney`, `useApiKeys`, `useTransactionList`.      |
| **A shared composable** (`composables/`)   | Behaviour that several features reuse and that carries no data of its own.                                                              | `useResource`, `useInfiniteList`, `useModal`, `useFormErrors`, `useDebouncedAutosave`. |
| **Local component state** (`ref` in the SFC) | Pure UI state nothing else needs.                                                                                                     | Which tab is active, whether a sheet is open, an input's draft text.        |

Rules of thumb:

- Start local, and move state up only when a second reader appears.
- A store that holds an entity type owns every mutation of it. Don't
  PATCH a budget from a feature composable and then `upsert` the result.
  Add or use a store action instead.
- Shared composables don't import `api` or stores; the architecture
  test enforces this. Pass them loader functions instead:
  `useResource(key, loader)`, `useInfiniteList(fetchFirst, fetchNext)`.
- A feature composable reads the active account from `accountContext`,
  or takes a getter (`useBudgetList(() => ctx.activeBankAccountId)`),
  so it reloads when the account changes.

---

## Testing stores

- `tests/setup.ts` gives each test a fresh Pinia with the reset plugin
  and an `api` bound to it.
- Seed state with `withAuth()` and `withAccounts(dtos, activeId?)` from
  `tests/helpers`.
- To check which actions a component calls, use
  `createTestingPinia({ createSpy: vi.fn, stubActions: false })`. In a
  setup store every returned function is an action, including getters
  like `byId`, so stubbed actions would return `undefined`.

See [testing.md](testing.md) for more.
