<script setup lang="ts">
//
// BudgetsView — budget list with filter tabs and section grouping.
// (UI_SPEC §4.2)
//
// Filter tabs: All | Recurring | Goals | Paused
// "All" tab shows two sections: Recurring then Goals.
// Type 'A' (ASSOCIATED_FILLUP_GOAL) budgets are not shown as standalone
// rows -- they appear only as the FillUpBand on their parent card.
// The unallocated budget is also excluded from the list.
//

// 3rd party imports
//
import { Fzf } from "fzf";
import { IconPlus, IconSearch, IconX } from "@tabler/icons-vue";
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";

// app imports
//
import BudgetCard from "@/components/budgets/BudgetCard.vue";
import AppShell from "@/components/layout/AppShell.vue";
import EmptyState from "@/components/shared/EmptyState.vue";
import MoneyAmount from "@/components/shared/MoneyAmount.vue";
import { fundingSummary as apiFundingSummary } from "@/api/bankAccounts";
import { listBudgets } from "@/api/budgets";
import { useAccountContextStore } from "@/stores/accountContext";
import { useBudgetsStore } from "@/stores/budgets";
import type { Budget, FundingSummary } from "@/types/api";

////////////////////////////////////////////////////////////////////////
//
const ctx = useAccountContextStore();
const budgets = useBudgetsStore();
const router = useRouter();

type Tab = "all" | "recurring" | "goals" | "capped" | "paused";
const activeTab = ref<Tab>("all");

const allBudgets = ref<Budget[]>([]);
const summary = ref<FundingSummary | null>(null);
const loading = ref(false);
const error = ref<string | null>(null);

////////////////////////////////////////////////////////////////////////
//
// Search state.
//
const searchOpen = ref(false);
const searchQuery = ref("");
let searchDebounce: ReturnType<typeof setTimeout> | null = null;
const searchMatchIds = ref<Set<string> | null>(null);

function onSearchInput() {
  const q = searchQuery.value.trim();
  if (!q) {
    searchMatchIds.value = null;
    return;
  }
  if (searchDebounce) clearTimeout(searchDebounce);
  searchDebounce = setTimeout(() => {
    const fzf = new Fzf(allBudgets.value, {
      selector: (b: Budget) => b.name,
      casing: "case-insensitive",
      fuzzy: false,
    });
    searchMatchIds.value = new Set(fzf.find(q).map((r) => r.item.id));
  }, 150);
}

const searchInput = ref<HTMLInputElement | null>(null);

function toggleSearch() {
  searchOpen.value = !searchOpen.value;
  if (!searchOpen.value) {
    searchQuery.value = "";
    searchMatchIds.value = null;
  } else {
    nextTick(() => searchInput.value?.focus());
  }
}

function onSearchKeydown(e: KeyboardEvent) {
  if (e.key === "f" && (e.metaKey || e.ctrlKey)) {
    e.preventDefault();
    if (!searchOpen.value) {
      searchOpen.value = true;
    }
    nextTick(() => searchInput.value?.focus());
  } else if (e.key === "Escape" && searchOpen.value) {
    toggleSearch();
  }
}

onMounted(() => window.addEventListener("keydown", onSearchKeydown));
onBeforeUnmount(() => window.removeEventListener("keydown", onSearchKeydown));

////////////////////////////////////////////////////////////////////////
//
// Map from fill-up budget UUID → Budget (type 'A' budgets).
//
const fillupMap = computed(() => {
  const map = new Map<string, Budget>();
  for (const b of allBudgets.value) {
    if (b.budget_type === "A") map.set(b.id, b);
  }
  return map;
});

function fillupFor(b: Budget): Budget | undefined {
  if (!b.fillup_goal) return undefined;
  return fillupMap.value.get(b.fillup_goal);
}

////////////////////////////////////////////////////////////////////////
//
// Budgets visible as standalone rows -- no type 'A', no unallocated.
//
const standaloneByTab = computed(() => {
  const unallocId = ctx.unallocatedBudgetId;
  const ids = searchMatchIds.value;
  let list = allBudgets.value.filter(
    (b) => b.budget_type !== "A" && b.id !== unallocId && (!ids || ids.has(b.id)),
  );
  switch (activeTab.value) {
    case "recurring":
      return list.filter((b) => b.budget_type === "R");
    case "goals":
      return list.filter((b) => b.budget_type === "G");
    case "capped":
      return list.filter((b) => b.budget_type === "C");
    case "paused":
      return list.filter((b) => b.paused);
    default:
      return list;
  }
});

const recurringBudgets = computed(() => standaloneByTab.value.filter((b) => b.budget_type === "R"));

const goalBudgets = computed(() => standaloneByTab.value.filter((b) => b.budget_type === "G"));

const cappedBudgets = computed(() => standaloneByTab.value.filter((b) => b.budget_type === "C"));

////////////////////////////////////////////////////////////////////////
//
async function load() {
  const accountId = ctx.activeBankAccountId;
  if (!accountId) return;
  loading.value = true;
  error.value = null;
  try {
    // Fetch all non-archived budgets so fill-up budgets are available
    // for the FillUpBand even when a filter tab is active.
    const [page, sum] = await Promise.all([
      listBudgets({ bank_account: accountId, archived: false, ordering: "name" }),
      apiFundingSummary(accountId),
    ]);
    allBudgets.value = page.results;
    summary.value = sum;
    // Push into shared cache so TopBar unallocated amount stays fresh.
    for (const b of page.results) budgets.upsert(b);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Failed to load budgets.";
  } finally {
    loading.value = false;
  }
}

watch(() => ctx.activeBankAccountId, load, { immediate: true });
</script>

<template>
  <AppShell>
    <template #action>
      <div class="flex items-center gap-1">
        <button
          type="button"
          class="flex h-10 w-10 items-center justify-center rounded-full text-neutral-700 hover:bg-neutral-100"
          aria-label="Search budgets"
          @click="toggleSearch"
        >
          <IconSearch v-if="!searchOpen" class="h-5 w-5" />
          <IconX v-else class="h-5 w-5" />
        </button>
        <button
          type="button"
          class="flex h-10 w-10 items-center justify-center rounded-full text-neutral-700 hover:bg-neutral-100"
          aria-label="Create budget"
          @click="router.push('/budgets/create/')"
        >
          <IconPlus class="h-5 w-5" />
        </button>
      </div>
    </template>

    <!-- Search bar -->
    <Transition
      enter-active-class="transition-all duration-200 ease-out"
      enter-from-class="max-h-0 opacity-0"
      enter-to-class="max-h-12 opacity-100"
      leave-active-class="transition-all duration-150 ease-in"
      leave-from-class="max-h-12 opacity-100"
      leave-to-class="max-h-0 opacity-0"
    >
      <div v-if="searchOpen" class="-mx-4 overflow-hidden px-4 pb-3">
        <input
          ref="searchInput"
          v-model="searchQuery"
          type="text"
          placeholder="Search budgets…"
          class="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-900 outline-none transition-colors placeholder:text-neutral-400 focus:border-ocean-400 focus:ring-1 focus:ring-ocean-400"
          @input="onSearchInput"
        />
      </div>
    </Transition>

    <!-- Filter tabs -->
    <div class="-mx-4 mb-4 flex border-b border-neutral-200 px-4 pt-3">
      <button
        v-for="tab in ['all', 'recurring', 'capped', 'goals', 'paused'] as Tab[]"
        :key="tab"
        type="button"
        class="mr-4 pb-2 text-sm font-medium capitalize transition-colors"
        :class="
          activeTab === tab
            ? 'border-b-2 border-ocean-400 text-ocean-600'
            : 'text-neutral-500 hover:text-neutral-700'
        "
        @click="activeTab = tab"
      >
        {{
          tab === "all"
            ? "All"
            : tab === "recurring"
              ? "Recurring"
              : tab === "capped"
                ? "Capped"
                : tab === "goals"
                  ? "Goals"
                  : "Paused"
        }}
      </button>
    </div>

    <!-- Funding summary banner -->
    <div
      v-if="summary && summary.total_amount !== '0' && summary.total_amount !== '0.00'"
      class="mb-4 rounded-card border border-ocean-200 bg-ocean-50 px-4 py-2.5 text-[13px] text-ocean-700"
    >
      Funded automatically:
      <MoneyAmount
        :amount="summary.total_amount"
        :currency="summary.currency"
        size="sm"
        class="font-medium"
      />/event
      <template v-if="summary.schedules.length > 1">
        across {{ summary.schedules.length }} schedules
      </template>
    </div>

    <!-- Loading skeletons -->
    <div v-if="loading" class="space-y-3">
      <div v-for="i in 4" :key="i" class="h-24 animate-pulse rounded-card bg-neutral-100" />
    </div>

    <!-- Error -->
    <div v-else-if="error" class="rounded-card bg-coral-50 px-4 py-3 text-sm text-coral-600">
      {{ error }}
    </div>

    <!-- "All" tab: two sections -->
    <template v-else-if="activeTab === 'all'">
      <!-- Recurring section -->
      <section v-if="recurringBudgets.length > 0">
        <h2 class="mb-2 text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
          Recurring
        </h2>
        <div class="space-y-3">
          <BudgetCard
            v-for="b in recurringBudgets"
            :key="b.id"
            :budget="b"
            :fillup-budget="fillupFor(b)"
          />
        </div>
      </section>

      <!-- Capped section -->
      <section v-if="cappedBudgets.length > 0" :class="recurringBudgets.length > 0 ? 'mt-6' : ''">
        <h2 class="mb-2 text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
          Capped
        </h2>
        <div class="space-y-3">
          <BudgetCard v-for="b in cappedBudgets" :key="b.id" :budget="b" />
        </div>
      </section>

      <!-- Goals section -->
      <section
        v-if="goalBudgets.length > 0"
        :class="recurringBudgets.length > 0 || cappedBudgets.length > 0 ? 'mt-6' : ''"
      >
        <h2 class="mb-2 text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
          Goals
        </h2>
        <div class="space-y-3">
          <BudgetCard v-for="b in goalBudgets" :key="b.id" :budget="b" />
        </div>
      </section>

      <!-- Empty state -->
      <EmptyState
        v-if="
          recurringBudgets.length === 0 && cappedBudgets.length === 0 && goalBudgets.length === 0
        "
        title="No budgets yet"
        message="Tap + to create your first budget."
      />
    </template>

    <!-- Filtered tabs: flat list -->
    <template v-else>
      <div v-if="standaloneByTab.length > 0" class="space-y-3">
        <BudgetCard
          v-for="b in standaloneByTab"
          :key="b.id"
          :budget="b"
          :fillup-budget="fillupFor(b)"
        />
      </div>
      <EmptyState
        v-else
        :title="
          activeTab === 'paused'
            ? 'No paused budgets'
            : activeTab === 'capped'
              ? 'No capped budgets'
              : 'No budgets in this category'
        "
        message="Try a different filter."
      />
    </template>
  </AppShell>
</template>
