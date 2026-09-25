# SPA architecture

The SPA in `frontend/src/` is split into layers. Each layer has one job
and may import only from the layers below it. `tests/architecture.test.ts`
checks the import rules on every test run, so a violation fails CI.

---

## Layers

```
                 ┌──────────────────────────────┐
                 │ views/          route shells │
                 └──────────────┬───────────────┘
                                │
                 ┌──────────────▼───────────────┐
                 │ features/<section>/          │
                 │   use*.ts   feature logic    │
                 │   *.vue     containers       │
                 └───┬──────────────────────┬───┘
                     │                      │
  ┌──────────────────▼─────┐   ┌────────────▼───────────────────┐
  │ components/            │   │ stores/       shared state     │
  │   presentational only  │   │ composables/  cross-feature    │
  └──────────────────┬─────┘   └────────────┬───────────────────┘
                     │                      │
                     │         ┌────────────▼───────────────────┐
                     │         │ api/          HTTP + resources │
                     │         └────────────┬───────────────────┘
                     │                      │
                 ┌───▼──────────────────────▼───┐
                 │ models/    domain types,     │
                 │            DTO ↔ model maps  │
                 └──────────────┬───────────────┘
                                │
                 ┌──────────────▼───────────────┐
                 │ domain/    pure TypeScript   │
                 └──────────────────────────────┘

  router/   route table, typed names, auth guard
  main.ts   composition root: wires Pinia, router, api, session
```

`api/` and `models/` sit side by side: `models/` imports the DTO types
from `api/dto.ts`, and the resource modules in `api/` never import
models. Stores and feature composables call the `api` and then map the
result with a model's `*FromDto` function.

| Layer          | Responsibility                                                                                          | May import                                                              | Must not import                                    |
|----------------|---------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------|----------------------------------------------------|
| `domain/`      | Money, local dates, RRULE text, budget status rules, enum labels. Pure functions and value types.      | 3rd-party pure libraries (`decimal.js`)                                 | Vue, Pinia, the router, any other `@/` layer       |
| `api/`         | The one `fetch` call (`http.ts`), errors, generated schema types, DTO aliases, one module per resource. | `domain/` (not used today)                                              | Vue, Pinia, the router, models and everything above |
| `models/`      | The shapes the UI works with (camelCase, `Money`, `LocalDate`) and the DTO ↔ model mappers.            | `domain/`, `@/api/dto`                                                  | the rest of `api/`, Vue, Pinia, everything above   |
| `stores/`      | Session and state shared across routes: entity caches, the active account, sign-out reset.              | `api/`, `models/`, `domain/`, Vue, Pinia                                | the router, components, features, views            |
| `composables/` | Behaviour reused across features: async state, modals, search, infinite lists, autosave, form errors.  | `domain/`, `models/`, `@/api/errors`, Vue                               | the rest of `api/`, stores, the router, UI layers  |
| `features/`    | One folder per section. Composables that load and mutate a section's data; container components.       | everything below, `components/`, the router                             | `views/`                                           |
| `components/`  | Presentational SFCs: props in, events out.                                                              | `domain/`, `models/` (types and pure helpers), `composables/`, other components | `api/`, `stores/`, `vue-router`, features, views |
| `views/`       | One per route. Reads route params, calls a feature composable, lays out features and components.        | everything except `api/`                                                | `api/`                                             |

The architecture test also checks that the only `fetch(` call in
`src/` is in `api/http.ts`.

### Why the rules exist

- **`domain/` is pure** so money and date rules are unit-tested with
  plain tables and reused anywhere, including the models.
- **`api/` knows nothing about the session.** The session store hands
  the transport callbacks (`getToken`, `refresh`, `onAuthFailure`), so
  the transport is tested without Pinia and could be reused outside the
  SPA.
- **Models are the only thing the UI sees.** Components never parse a
  decimal string or a date string; the mapping happens once, in one
  place, with tests.
- **Components are presentational** so they render the same way in
  every context and are tested with props alone. Loading, saving and
  navigating belong to the feature that uses them.
- **Views never call the API** so every request goes through a store or
  a feature composable. That is where caching, stale-response guards
  and error messages live.

---

## Naming

| Kind                   | Convention                                   | Example                                   |
|------------------------|----------------------------------------------|-------------------------------------------|
| Domain module          | lower camelCase noun                         | `domain/budgetStatus.ts`                  |
| Resource module        | `api/resources/<resource>.ts`, `<resource>Resource(http)` | `budgetsResource` → `api.budgets` |
| DTO type               | `<Thing>Dto`, `<Thing>CreateDto`, `<Thing>UpdateDto`, `<Thing>ListQuery` | `BudgetDto`, `BudgetListQuery` |
| Model type             | the plain noun                               | `Budget`, `Transaction`                   |
| Mapper                 | `<thing>FromDto`, `<thing>ToCreateDto`, `<thing>ToUpdateDto` | `budgetFromDto`               |
| Store                  | `stores/<noun>.ts`, `use<Noun>Store`, id = file name | `useBudgetsStore` (`"budgets"`)   |
| Composable             | `use<Behaviour>`, one per file               | `useInfiniteList`                         |
| Feature composable     | `features/<section>/use<Thing>.ts`           | `features/budgets/useMoveMoney.ts`        |
| Container component    | `features/<section>/<Thing>Section.vue` / `<Thing>Sheet.vue` | `features/budgets/MoveMoneySheet.vue` |
| Presentational component | `components/<section>/<Thing>.vue`, or `components/shared/` | `components/budgets/BudgetCard.vue` |
| View                   | `views/<Page>View.vue`                       | `views/BudgetDetailView.vue`              |
| Route name             | kebab-case, declared in `router/types.ts`    | `budget-detail`                           |

Every module starts with a header comment that says what it is for and
which layer it belongs to (`Store layer.`, `Feature composable
(budgets).`, ...).

---

## Request lifecycle

A request from a feature to the server and back:

```
view ──► feature composable / store
           │  api.budgets.get(id)
           ▼
         api/resources/budgets.ts ──► http.get("/api/v1/budgets/<id>/")
                                          │
                                          ▼
                                     api/http.ts
                                       1. Authorization: Bearer <getToken()>
                                       2. fetch
                                       3. 401? ──► refresh() (single-flight)
                                                     ok  ──► retry once
                                                     fail──► onAuthFailure(AuthError)
                                                              throw AuthError
                                       4. other non-2xx ──► throw ApiError
                                       5. 2xx ──► parsed JSON (or null)
           ▲
           │  BudgetDto
         budgetFromDto(dto) ──► Budget ──► store cache / composable state
```

1. **Wiring.** `main.ts` builds the client with
   `createSessionHttpClient({ onAuthFailure })` from `stores/session.ts`
   and hands it to `initApi()`. The session store supplies the token
   (`accessToken`) and the refresh (`renewToken()`, which posts to
   `/api/token/refresh/` with the httpOnly cookie).
2. **The 401 refresh.** On a 401, `http.ts` calls its `refresh()`.
   Concurrent 401s share one refresh request, because the backend
   rotates the refresh cookie and blacklists the old one: a second
   parallel refresh would carry a dead cookie and end a session the
   first one just renewed. The original request is retried once with
   the new token.
3. **AuthError.** When the refresh fails, the session-wired client calls
   `session.logout()` (which resets every store) and then the
   `onAuthFailure` callback from `main.ts`, which calls
   `redirectToLogin(router)`: the user lands on `/app/login/?next=<the
   page they were on>`. The request then rejects with `AuthError`;
   callers need not handle it beyond showing `describeError(err)`.
4. **ApiError.** Any other non-2xx rejects with `ApiError`, which parses
   DRF's error body into `detail`, `fieldErrors` and `nonFieldErrors`.
   `useFormErrors().setError(err)` puts them next to the right inputs;
   `describeError(err)` gives a one-line message for a banner.

See [api-and-models.md](api-and-models.md) for the transport's options
and the error shape.

---

## How sections communicate

Sections never import each other's composables or reach into each
other's state. They share data in two ways:

- **Through a store**, when the data outlives one page or one section
  shows what another changed. The entity caches (`budgets`,
  `bankAccounts`, `allocations`) update themselves from the server's
  answer to every mutation, so every reader sees the change.
- **Through props and events**, between a view and the features and
  components it lays out.

For example, moving money between budgets on the budget detail page
changes the Unallocated balance the top bar shows. Neither knows about
the other:

```ts
// features/budgets/useMoveMoney.ts -- the move-money sheet's logic
await store.transfer({ bankAccountId, srcBudgetId, dstBudgetId, amount });

// stores/budgets.ts -- create the transfer, then refetch both budgets into the cache
async function transfer(input: TransferInput): Promise<void> {
  await api.internalTransactions.create(transferToCreateDto(input));
  await Promise.all([fetchOne(input.srcBudgetId), fetchOne(input.dstBudgetId)]);
}

// features/shell/AppShell.vue -- the top bar's container
const unallocated = computed(() => budgets.byId(ctx.unallocatedBudgetId)?.balance ?? null);
```

When one side of the transfer is the Unallocated budget, `AppShell`'s
computed re-evaluates and the top bar updates. The budget detail page
reads its budget from the same cache, so its hero updates too.

The view wires the sheet to its own state with props and an event:

```vue
<!-- views/BudgetDetailView.vue -->
<MoveMoneySheet
  :open="showMoveMoneyForm"
  :budget="budget"
  :fillup-budget="fillupBudget"
  @close="showMoveMoneyForm = false"
/>
```

---

## Related documents

- [api-and-models.md](api-and-models.md) — the transport, errors, types, models, adding a resource
- [state.md](state.md) — stores, caching, sign-out reset
- [components.md](components.md) — presentational vs feature components
- [adding-a-page.md](adding-a-page.md) — a new page end to end
- [testing.md](testing.md) — tests for each layer
