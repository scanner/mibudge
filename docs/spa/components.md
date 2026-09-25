# Components

The SPA has two kinds of component: presentational components in
`src/components/`, and feature (container) components in
`src/features/<section>/`. Views in `src/views/` are route shells that
compose both. See [architecture.md](architecture.md) for the import
rules, which `tests/architecture.test.ts` enforces.

---

## Presentational vs feature components

|                  | Presentational (`components/`)                                             | Feature / container (`features/<section>/`)                                    |
|------------------|----------------------------------------------------------------------------|---------------------------------------------------------------------------------|
| Gets data from   | props only                                                                  | a feature composable, stores, the router                                        |
| Reports changes  | emits events; `defineModel` for two-way-bound inputs                        | calls actions, navigates, emits to its view                                     |
| May import       | `domain/`, `models/` (types and pure helpers), `composables/`, other components | anything except `views/`                                                    |
| Must not import  | `@/api`, `@/stores`, `vue-router`, `features/`, `views/`                    | `views/`                                                                        |
| Tested with      | `mount(Component, { props })`, asserting on output and `emitted()`          | `mountWithApp` with the mock API, or through its view's test                    |
| Examples         | `BudgetCard`, `MoneyAmount`, `TransactionRow`, `ConfirmSheet`, `TopBar`     | `AppShell`, `MoveMoneySheet`, `BudgetTransactionsSection`, `PasswordSection`    |

A presentational component renders the same way wherever it is used.
If it needs to load, save or navigate, it emits an event and lets its
parent do it. For example, `BudgetCard` emits `select` with the budget
id, and `BudgetsView` pushes `{ name: "budget-detail", params: { id } }`.

A feature component is a section of a page with its own behaviour. Its
logic lives in a sibling composable (`MoveMoneySheet.vue` +
`useMoveMoney.ts`), so the component file is mostly template, and the
logic can be tested without mounting.

`features/shell/AppShell.vue` is the container for the presentational
`TopBar`, `SideNav`, `BottomNav` and `AccountSwitcher`. It reads the
account context and the budget cache and passes models down.

---

## Props

- Declare props with a type: `defineProps<{ budget: Budget; fillupBudget?: Budget }>()`.
  Use `withDefaults` for optional props that have a default.
- Pass **models**, not DTOs or raw strings. An amount is a `Money`, a
  calendar date is a `LocalDate`, and a budget is a `Budget`. Components
  never parse decimal or date strings.
- Pass the smallest thing the component needs. `TopBar` takes
  `account: BankAccount | null` and `unallocated: Money | null`, not the
  whole account-context store.
- Lookups the component needs (budget names by id, the Unallocated
  budget id) are props, computed by the parent from a store.
- Never mutate a prop. Emit an event, or use `defineModel` (below).

## Emits

- Declare events with a type:

  ```ts
  const emit = defineEmits<{
    (e: "select", budgetId: string): void;
    (e: "close"): void;
  }>();
  ```

- Name events for what happened in the component, not what the parent
  should do:
  - `select`, `close`, `confirm`, `cancel`, `back`;
  - `save` / `submit` with the form value;
  - `switch-account`.
- Emit ids or models, not DOM events.

## `defineModel`

Use `defineModel` when the parent owns a value and the component edits
it directly: a text input inside a presentational card, bound to a
feature composable's ref.

```ts
// components/bankAccounts/BankAccountHeader.vue
const name = defineModel<string>("name", { required: true });
```

```vue
<!-- views/BankAccountDetailView.vue -->
<BankAccountHeader
  v-model:name="detail.editName.value"
  v-model:account-number="detail.editAccountNumber.value"
  :account="account"
  @edit="detail.startEdit"
  ...
/>
```

Name each model after the value (`v-model:name`, `v-model:email`), and
don't use a bare `v-model` for a component that edits more than one
value. Actions on the value (save, cancel) are still events.

## Modals and sheets

Sheets and dialogs call `useModal(() => props.open, () => emit("close"))`.
It provides the shared behaviour and nothing else:

- a reference-counted body scroll lock;
- Escape closes only the topmost modal;
- focus returns to where it was when the modal closes.

The component keeps its own markup, `Teleport` and transitions. Don't
add `@keydown.esc` handlers to sheet markup; `useModal` handles Escape.

## Styling

Components use Tailwind utility classes directly in their templates, as
described in `docs/UI_SPEC.md` §2–3. When you move markup between
components, move it verbatim, classes included. A refactor never
restyles.

---

## Naming and placement

| What                                  | Where                                          | Name                                  |
|---------------------------------------|------------------------------------------------|---------------------------------------|
| Presentational, one section           | `components/<section>/`                        | `<Thing>.vue`, e.g. `BudgetCard.vue`  |
| Presentational, used across sections  | `components/shared/`                           | `MoneyAmount.vue`, `ConfirmSheet.vue` |
| App chrome                            | `components/layout/`                           | `TopBar.vue`, `SideNav.vue`           |
| Feature component                     | `features/<section>/`                          | `<Thing>Section.vue`, `<Thing>Sheet.vue`, `<Thing>Form.vue` |
| Its logic                             | `features/<section>/`, next to it              | `use<Thing>.ts`                       |
| Route shell                           | `views/`                                       | `<Page>View.vue`                      |

- `<section>` is the product area: `budgets`, `transactions`,
  `bankAccounts`, `settings`, `overview`, `auth` or `shell`.
- File names are PascalCase and match the component name.
- In templates, refer to components in PascalCase
  (`<MoneyAmount :amount="..." />`) and to props and events in
  kebab-case (`:fillup-budget`, `@switch-account`).
- Every SFC opens its `<script setup>` with a header comment. It names
  the component, says what it shows, and states its kind ("Feature
  component (budgets)", or which events it emits).

---

## Testing components

- **Presentational:** mount with props and assert on the rendered text,
  attributes and `wrapper.emitted()`. No mock API is needed.
- **Feature:** `mountWithApp(Component, { route, props })` from
  `tests/helpers`. It uses the real router, the active Pinia, and the
  MSW mock API.
- **Which store actions a container calls:** use
  `createTestingPinia({ createSpy: vi.fn, stubActions: false })`.

See [testing.md](testing.md).
