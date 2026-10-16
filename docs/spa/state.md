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
| `session`           | `stores/session.ts`        | The in-memory access token, the signed-in `user`, `isAuthenticated` and the profile `timezone`. Sign-in (`login`), token renewal (`renewToken`, `refresh`), `loadUser`, `updateProfile`, `logout`, `endSession`. Also builds the session-wired HTTP client (`createSessionHttpClient`). |
| `bankAccounts`      | `stores/bankAccounts.ts`   | The user's bank accounts, in list order. `loadAll`, `refresh`, `invalidate`, `fetchOne`, `create`, `update`, `remove`; read with `all` and `byId`. |
| `accountContext`    | `stores/accountContext.ts` | Which account the user is looking at: `activeBankAccountId`, `activeBankAccount`, `unallocatedBudgetId`. `init()` picks the account: the one stored for this tab, else the user's default, else the first. `refresh()` moves off a deleted account. The choice persists per tab in `sessionStorage`. |
| `budgets`           | `stores/budgets.ts`        | Budgets keyed by id. `fetchOne`, `fetchList` (every page), `refreshAccount`, `create`, `update`, `archive`, `transfer`; read with `byId`, `forAccount`, `names`. |
| `transactionNav`    | `stores/transactionNav.ts` | The ids of the rows the transaction list last showed, so the detail page can step to the previous or next row. It also keeps the list's search and filter across a visit to the detail page. |
| `invalidation`      | `stores/invalidation.ts`   | The signal that data may have changed on the server, and the subscribers that refetch what they show. `invalidate(scope)`, `pageShown(hiddenMs)`, `onInvalidate(interest, refresh)`. See [Keeping shown data current](#keeping-shown-data-current). |

`stores/reset.ts` and `stores/writeOrder.ts` are not stores. They hold
the reset plugin (below) and the caches' write order.

---

## Caching and invalidation

The entity caches (`bankAccounts`, `budgets`) follow the same rules:

- **Readers read from the cache.** Views and features use `byId`,
  `forAccount` and `all`, all computed from the cached models. A
  feature that loads data (`useBudgetDetail`, `useOverview`) calls the
  store's fetch action and then reads the result back through `byId`,
  not from the fetch's return value. That way a later update by
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
  `fetchOne` for the two ends of a transfer. The split's answer (the
  transaction's new allocations) replaces the ones the detail page
  shows.
- **Transactions are not cached.** A bank sync gives pending
  transactions new ids, and a co-owner can re-split a transaction from
  another browser, so the transaction lists (the account's list and a
  budget's) load their pages each time they open. Each transaction
  carries its allocations, so a row's budgets are always those of the
  page it came in.
- **`invalidate` marks data stale without fetching.** The next read
  refetches:
  - `bankAccounts.invalidate()`: the next `loadAll()` refetches.
  - `budgets.invalidate(ids?)`: drops the given entries, or all of them.

  Use it when you know data changed but nothing is on screen to refetch
  it now.
- **Answers are written in order.** The `budgets` and `bankAccounts`
  caches write through `createWriteOrder()` (`stores/writeOrder.ts`).
  A fetch takes a ticket before it sends its request and writes a
  record only if no newer answer for it is cached. A mutation marks
  its records as in flight, and on success as written at the moment
  it landed. So a fetch answered before a save landed, or before a
  later fetch was answered, never puts an older value back on screen.
  The bank-account list's membership follows the same rule: a list
  answer older than the last create or remove is dropped, and
  concurrent list loads share one request.
- **Loads are guarded against stale responses.** Anything keyed on the
  active account or a route param loads through `useResource` /
  `useAsync` (see [composables](#store-vs-composable-vs-local-state)).
  Those drop a response that arrives after the key has changed, so
  switching accounts quickly never shows the previous account's data.

A store does not hold loading or error state for a single page. The
budgets store's `loading` / `error` describe its last list fetch;
per-page state comes from `useResource` in the feature composable.

---

## Keeping shown data current

Data changes on the server without this tab doing anything: a bank
sync posts pending transactions, a funding run moves money between
budgets, a co-owner edits from another browser, an importer adds
transactions. The SPA keeps what is on screen current with one
signal, `stores/invalidation.ts`, which has sources on one side and
subscribers on the other.

```
 sources                         signal                      subscribers
 ───────                         ──────                      ───────────
 page shown after 60s hidden ─┐                          ┌─► AppShell: account list,
 network back online ─────────┤                          │   Unallocated budget
 pull to refresh / Refresh ───┼─► invalidate(scope) ─────┼─► useOverview, useBudgetList, ...
 server events (one day) ─────┘    coalesce per tick,    └─► each refetches what it shows
                                   hold while hidden         through its store or load
```

- **A signal says what may have changed, never the data.** A scope
  names a bank account and kinds of data: `bankAccounts` (bank account
  records, balances), `budgets` (budget records, balances, funding
  summaries) and `transactions` (transactions, their allocations,
  transfers). An omitted field means every value, so
  `invalidate()` means everything. A source that knows more sends a
  narrower scope, and fewer subscribers refetch.
- **Subscribers say what they show.** A feature composable that loads
  a page's data subscribes with
  `onInvalidate(interest, refresh)`. `interest()` returns the bank
  account and kinds the page shows (`accountInterest(id, kinds)`), or
  `null` while it shows nothing. The subscription ends with the
  component that made it. `refresh` reloads through the same store
  actions and loads the page used to load, in the background.
- **Signals coalesce, and wait while the page is hidden.** Signals
  raised in the same tick run each matching subscriber once. A signal
  raised while the page is hidden is held and flushed when the page is
  shown again, so nothing is fetched for a page no one is looking at.
  `invalidate()` resolves once the refreshes it started have settled,
  which is when the pull-to-refresh spinner stops.
- **The sources.** `main.ts` calls `useRefreshOnReturn()`
  (`features/shell/`), which connects `usePageReturn` to the store:
  the page shown again after at least `STALE_AFTER_MS` (60 seconds)
  hidden signals everything (`pageShown`), and so does the network
  coming back. The user signals everything on demand by pulling down
  from the top of the page on a touch screen (`usePullToRefresh`; not
  inside an open sheet) or with the Refresh button in the side
  navigation. `overscroll-behavior-y: contain` on `html` keeps the
  browser's own pull-to-refresh from reloading the page. A server event
  stream calls `invalidate()` with narrow scopes; with it, the
  shown-again refresh is the fallback for missed events and its
  threshold can grow.
- **A background refresh keeps the page on screen.**
  `useResource().refresh()` and `useInfiniteList().refresh()` leave
  `loading` false and the shown data in place, and replace it when
  the answer arrives. A failed refresh keeps the shown data and shows
  no error; the next signal tries again. A 404 is the exception: the
  record is gone (a bank sync replaces pending transactions, a
  co-owner deletes a bank account), so the page shows the error it
  would show on opening a link to a missing record. A refresh loses
  to a load for a new key (an account switch, a route param), like any
  stale response.
- **A scrolled list refreshes as deep as it was scrolled.**
  `useInfiniteList().refresh()` asks for the loaded rows plus
  headroom in one page (following `next` past the server's largest
  page) and swaps them in at once. Rows are keyed by id where they
  are rendered, so a changed row updates in place, a new one appears
  above and a deleted one disappears. Rows are not matched by id
  across the swap, because a bank sync gives pending transactions new
  ids. The reader's place in the list is held by the browser's scroll
  anchoring, which keeps the rows on screen still when rows are
  inserted above them.
- **Edits in progress survive a refresh.** An optimistic setting
  shows its pending value until its request lands, and the write
  order keeps that request's answer over an older refresh answer. On
  the transaction detail page a refresh updates the transaction but
  leaves the description and memo alone while they hold text not yet
  saved, and drops its answer if the page saved, split or uploaded
  meanwhile. Forms copy their record when they open, so a refresh
  does not reset them.

Store actions named `invalidate` (`budgets.invalidate(ids)`,
`bankAccounts.invalidate()`) are a different tool: they mark cached
data stale for the next read, without fetching or signalling
anyone.

---

## Settings that save on change

A control that saves as soon as the user changes it (a toggle, a
select) is optimistic: the new value shows at once and the request runs
in the background. The feature composable wraps the setting in
`useOptimistic(source, commit, options?)` from
`composables/useOptimistic.ts`. It never hand-rolls a pending value.

```ts
// features/bankAccounts/useBankAccountDetail.ts
const autoFunding = useOptimistic(
  (accountId: string) => accounts.byId(accountId)?.autoFundingEnabled ?? false,
  async (accountId: string, enabled: boolean) => {
    await accounts.update(accountId, { autoFundingEnabled: enabled });
  },
  { errorMessage: "Failed to change automatic funding." },
);
const autoFundingEnabled = computed(() =>
  account.value ? autoFunding.value(account.value.id) : false,
);
```

- **Everything is keyed** by the record the setting belongs to (an
  account id, a notification kind, or a fixed key such as `"default"`
  for a single setting). `value(key)`, `saving(key)` and `error(key)`
  all take the key, so one composable serves every record on a page,
  and a view that moves to another record never shows the last one's
  state.
- **`source(key)` is the saved value, and `commit` writes the server's
  answer into it.** Usually `source` reads a store cache and `commit`
  calls the store's update action, which writes the cache. A `commit`
  that does not update what `source` reads makes the control snap back
  to the old value once the request finishes.
- **`set(key, value)`** shows `value` at once, clears the key's error
  and saves. Bind the control to `value(key)` and its change event to
  `set`.
- **One request per key at a time.** Requests for a key run in the
  order the user made the changes, so the server ends with the user's
  last choice and the answers reach `source` in order. Changes made
  while a request is in flight coalesce: only the latest is sent next.
  Different keys save independently.
- **When a key's last request finishes**, the pending value is dropped
  and `value(key)` reads `source` again: the server's answer after a
  success, the unchanged saved value after a failure. A refused change
  therefore shows the saved value, and `error(key)` says why
  (`describeError`, with `errorMessage` as the fallback). A failure that a later queued
  change supersedes is not reported.

A text field that saves after the user stops typing uses
`useDebouncedAutosave` instead.

---

## Sign-out resets every store

`main.ts` and `tests/setup.ts` install `resetPlugin` from
`stores/reset.ts` on the Pinia. The plugin records each store as it is
created. `resetAllStores(pinia)` then calls every recorded store's
`reset()`.

`session.endSession()` calls `resetAllStores`. It runs on:

- **Sign-out.** `features/auth/useSignOut.ts` awaits `logout()`, which
  posts to `/api/token/logout/` so the server revokes the refresh cookie,
  then calls `endSession()`; the reset happens even when that request
  fails. The login page opens after `logout()` finishes, so the
  cookie-clearing answer cannot land after a new sign-in.
- **Session end.** When a token refresh fails, the session-wired HTTP
  client calls `endSession()` before `main.ts`'s `onAuthFailure`
  redirects to `/app/login/?next=<path>`. The cookie is already dead, so
  no logout request is sent.

After a reset no cached account, budget, navigation list or
stored active-account id survives into the next user's session in the
same tab.

**Every store must define `reset()`** that returns all of its state to
the initial values (and clears anything it persisted).
`tests/stores/reset.test.ts` globs `src/stores/*.ts` and fails if any
store has no `reset`. It also seeds every store, signs out, and checks
that every store is empty and the tab's stored account is gone. When you
add a store, add its state to that sign-out test.

**A request in flight at sign-out must not write afterwards.** A store
that caches server answers creates a guard with `createSessionGuard()`
(`stores/reset.ts`), calls `guard.bump()` in `reset()`, and wraps each
cache write in `guard.whileCurrent(...)` before it awaits the request.
The budgets and bank-accounts stores do this; the session store compares
its own in-flight promise instead.
`tests/stores/reset.test.ts` checks that a late answer leaves the store
empty.

---

## Store vs composable vs local state

| Put it in…                                 | When                                                                                                                                    | Examples                                                                    |
|--------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------|
| **A store** (`stores/`)                    | More than one route or section reads it, it must outlive the page, or one section must see another's change.                           | The session, the active account, the budget cache the top bar and budget pages share, the transaction list's row order for the detail page's prev/next. |
| **A feature composable** (`features/<section>/use*.ts`) | Data and actions belonging to one section. It loads through `api` or a store, holds the section's form state, and exposes computed views of it. | `useBudgetDetail`, `useMoveMoney`, `useApiKeys`, `useTransactionList`.      |
| **A shared composable** (`composables/`)   | Behaviour that several features reuse and that carries no data of its own.                                                              | `useResource`, `useInfiniteList`, `useModal`, `useFormErrors`, `useOptimistic`, `useDebouncedAutosave`. |
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
