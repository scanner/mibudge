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
import { IconPlus } from "@tabler/icons-vue";
import { computed, ref, watch } from "vue";
import { useRouter } from "vue-router";

// app imports
//
import BudgetCard from "@/components/budgets/BudgetCard.vue";
import AppShell from "@/components/layout/AppShell.vue";
import EmptyState from "@/components/shared/EmptyState.vue";
import { listBudgets } from "@/api/budgets";
import { useAccountContextStore } from "@/stores/accountContext";
import { useBudgetsStore } from "@/stores/budgets";
import type { Budget } from "@/types/api";

////////////////////////////////////////////////////////////////////////
//
const ctx = useAccountContextStore();
const budgets = useBudgetsStore();
const router = useRouter();

type Tab = "all" | "recurring" | "goals" | "capped" | "paused";
const activeTab = ref<Tab>("all");

const allBudgets = ref<Budget[]>([]);
const loading = ref(false);
const error = ref<string | null>(null);

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
  let list = allBudgets.value.filter((b) => b.budget_type !== "A" && b.id !== unallocId);
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
    const page = await listBudgets({ bank_account: accountId, archived: false, ordering: "name" });
    allBudgets.value = page.results;
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
      <button
        type="button"
        class="flex h-10 w-10 items-center justify-center rounded-full text-neutral-700 hover:bg-neutral-100"
        aria-label="Create budget"
        @click="router.push('/budgets/create/')"
      >
        <IconPlus class="h-5 w-5" />
      </button>
    </template>

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
