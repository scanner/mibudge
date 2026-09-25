# Adding a page

A recipe for adding a route to the SPA, with a worked minimal example.
After it comes a guide to moving an existing view onto the layers one
step at a time. Read [architecture.md](architecture.md) first for what
each layer may import.

---

## The recipe

1. **Data.** Make sure the API resource and the model exist. If not,
   add them first ([api-and-models.md](api-and-models.md#adding-a-rest-resource-end-to-end)).
2. **Feature composable.** Create `features/<section>/use<Thing>.ts`.
   It loads the page's data (through a store, or `api` + a mapper),
   exposes it as computed refs, and holds the page's actions. Use
   `useResource(key, loader)` so a key change reloads and a stale
   response is dropped.
3. **Components.** Build presentational pieces in
   `components/<section>/` (props in, events out). Anything that needs a
   store, `api` or the router is a container, and goes in
   `features/<section>/` ([components.md](components.md)).
4. **View.** Create `views/<Page>View.vue`, a route shell. It takes
   route params as props, calls the feature composable, lays out
   `AppShell` plus the features and components, and navigates by route
   name. It stays under 400 lines. If it grows, move a section into a
   feature component.
5. **Route.**
   - Add the name, path and params to `AppRouteNamedMap` in
     `router/types.ts`.
   - Add the record to `routes` in `router/index.ts`, with
     `meta: AUTHENTICATED` (or `PUBLIC`).
   - If the path has an `:id`, add `props: true`.
6. **Navigation.** If the page needs a nav entry, add it to
   `components/layout/BottomNav.vue` and `SideNav.vue` as
   `to: { name: "<route>" }`.
7. **Tests:**
   - The feature composable, through `withSetup` or a view test.
   - The view with `mountWithApp`: data from the mock API renders, the
     error state shows, and navigation lands.
   - A `tests/router/guards.test.ts` row if the route is public.

   `vue-tsc` checks the typed route names.
8. **Check.** Run `pnpm fmt && pnpm type-check && pnpm test:coverage`.

---

## Worked example: a categories page

This example adds a read-only page at `/app/categories/` that lists the
transaction categories, grouped by `group`. The resource
(`api.transactionCategories.list`) and the model
(`transactionCategoryFromDto`) already exist.

### Feature composable

```ts
// src/features/categories/useCategoryList.ts
//
// `useCategoryList`: every transaction category the user can see,
// grouped by `group`.  Feature composable (categories).
//

// 3rd party imports
//
import { computed } from "vue";

// app imports
//
import { api } from "@/api";
import { useResource } from "@/composables/useResource";
import type { TransactionCategory } from "@/models/transactionCategory";
import { transactionCategoryFromDto } from "@/models/transactionCategory";

////////////////////////////////////////////////////////////////////////
//
export function useCategoryList() {
  // A constant key: load once when the page mounts.
  const resource = useResource(
    () => "all",
    async () => {
      const first = await api.transactionCategories.list({ archived: false });
      return (await api.pages.all(first)).map(transactionCategoryFromDto);
    },
    { errorMessage: "Failed to load categories." },
  );

  const groups = computed(() => {
    const byGroup = new Map<string, TransactionCategory[]>();
    for (const c of resource.data.value ?? []) {
      byGroup.set(c.group, [...(byGroup.get(c.group) ?? []), c]);
    }
    return [...byGroup].map(([group, categories]) => ({ group, categories }));
  });

  return { groups, loading: resource.loading, error: resource.error };
}
```

### Presentational component

```vue
<!-- src/components/categories/CategoryGroup.vue -->
<script setup lang="ts">
//
// CategoryGroup — one category group as a titled list.  Presentational:
// emits `select` with the category id.
//

// app imports
//
import type { TransactionCategory } from "@/models/transactionCategory";

////////////////////////////////////////////////////////////////////////
//
defineProps<{ group: string; categories: TransactionCategory[] }>();
const emit = defineEmits<{ (e: "select", id: string): void }>();
</script>

<template>
  <section>
    <h2 class="mb-2 text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
      {{ group }}
    </h2>
    <ul class="divide-y divide-neutral-100 rounded-card border border-neutral-200 bg-white">
      <li
        v-for="c in categories"
        :key="c.id"
        class="cursor-pointer px-4 py-3 text-[14px] hover:bg-neutral-50"
        @click="emit('select', c.id)"
      >
        {{ c.name }}
      </li>
    </ul>
  </section>
</template>
```

### View

```vue
<!-- src/views/CategoriesView.vue -->
<script setup lang="ts">
//
// CategoriesView — transaction categories by group.  Route shell over
// `useCategoryList`.
//

// app imports
//
import CategoryGroup from "@/components/categories/CategoryGroup.vue";
import { useCategoryList } from "@/features/categories/useCategoryList";
import AppShell from "@/features/shell/AppShell.vue";

////////////////////////////////////////////////////////////////////////
//
const { groups, loading, error } = useCategoryList();
</script>

<template>
  <AppShell>
    <div class="space-y-5 py-2">
      <div v-if="loading" class="h-16 animate-pulse rounded-card bg-neutral-100" />
      <div v-else-if="error" class="rounded-card bg-coral-50 px-4 py-3 text-sm text-coral-600" role="alert">
        {{ error }}
      </div>
      <CategoryGroup
        v-for="g in groups"
        v-else
        :key="g.group"
        :group="g.group"
        :categories="g.categories"
      />
    </div>
  </AppShell>
</template>
```

### Route

```ts
// src/router/types.ts -- in AppRouteNamedMap
categories: RouteRecordInfo<"categories", "/categories/", NoParams, NoParams>;

// src/router/index.ts -- in routes
{
  path: "/categories/",
  name: "categories",
  component: () => import("@/views/CategoriesView.vue"),
  meta: AUTHENTICATED,
},
```

Elsewhere, navigate with `router.push({ name: "categories" })` or
`<RouterLink :to="{ name: 'categories' }">`.

### Test

```ts
// tests/views/CategoriesView.test.ts
describe("CategoriesView", () => {
  beforeEach(() => {
    withAuth();
    withAccounts([makeBankAccount()]);
  });

  // GIVEN: categories in two groups
  // WHEN:  the categories page is opened
  // THEN:  each group is shown with its categories
  //
  it("lists categories by group", async () => {
    server.use(
      http.get("/api/v1/transaction-categories/", () =>
        HttpResponse.json(
          makePage([
            makeCategory({ group: "Food", name: "Groceries" }),
            makeCategory({ group: "Home", name: "Rent" }),
          ]),
        ),
      ),
    );

    const { wrapper } = await mountWithApp(CategoriesView, { route: "/categories/" });

    expect(wrapper.findAll("h2").map((h) => h.text())).toEqual(["Food", "Home"]);
  });
});
```

### A page with an `:id`

A detail page takes the id as a prop (`props: true` on the route) and
passes a getter to its feature composable:

```ts
const props = defineProps<{ id: string }>();
const { budget, loading, error } = useBudgetDetail(() => props.id);
```

When the user moves from one budget to another, Vue Router reuses the
view instance, so a value read once in `setup` would go stale. The
getter makes `useResource` reload on every new id. Other per-id state
(an open sheet, a draft) is cleared with `watch(() => props.id, ...)`,
as `BudgetDetailView.vue` does.

---

## Rewriting an existing view incrementally

A large view that loads its own data and mixes several sections can move
onto the layers in small, separately testable steps. Each step leaves
the app working and the tests green. Do them in this order:

1. **Pin the behaviour.** If the view has no test, add a
   `tests/views/<View>.test.ts` covering what it renders from the mock
   API and what it sends on its main actions. This test must still pass
   unchanged at the end.
2. **Replace raw values with models.** Where the view parses money or
   dates itself (`parseFloat`, `new Date("YYYY-MM-DD")`), switch to the
   model's fields (`Money`, `LocalDate`) and the `domain/` formatters.
3. **Extract the data logic.** Move loads, mutations and the state they
   drive into `features/<section>/use<Thing>.ts`. The template keeps
   binding the same names, destructured from the composable. Replace
   hand-rolled "ignore stale response" flags with `useResource` /
   `useAsync`. Replace direct `api` calls for shared entities with store
   actions.
4. **Extract sections.**
   - A section with only markup and props becomes a presentational
     component in `components/<section>/`.
   - A section with its own logic (a sheet, a form) becomes a container
     in `features/<section>/` with its own composable.
   - Move markup and classes verbatim.
5. **Swap shared behaviour for composables:**
   - `useModal` for scroll lock, Escape and focus return;
   - `useFormErrors` for DRF field errors;
   - `useInfiniteList` for paging;
   - `useDebouncedAutosave` for autosave fields.
6. **Route it by name.** Take the id as a prop and navigate with
   `{ name, params }`.

After each step, run `pnpm type-check && pnpm test`. When the view no
longer imports `@/api`, the architecture test keeps it that way.
