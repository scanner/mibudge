//
// Budgets store — caches Budget objects keyed by UUID.  Views fetch
// their own slices; shared consumers (e.g. TopBar reading the
// unallocated balance) look up by id.
//
// Phase 2 covers fetch-one and a small list loader; Phase 3 adds the
// filtered-list cache used by the Budgets view.
//

// 3rd party imports
//
import { defineStore } from "pinia";
import { computed, ref } from "vue";

// app imports
//
import * as api from "@/api/budgets";
import type { Budget, BudgetListParams } from "@/types/api";

////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////
//
export const useBudgetsStore = defineStore("budgets", () => {
  ////////////////////////////////////////////////////////////////////
  //
  const cache = ref(new Map<string, Budget>());
  const loading = ref(false);
  const error = ref<string | null>(null);

  const all = computed(() => Array.from(cache.value.values()));

  ////////////////////////////////////////////////////////////////////
  //
  function byId(id: string): Budget | null {
    return cache.value.get(id) ?? null;
  }

  ////////////////////////////////////////////////////////////////////
  //
  function upsert(budget: Budget) {
    cache.value.set(budget.id, budget);
  }

  ////////////////////////////////////////////////////////////////////
  //
  async function fetchOne(id: string): Promise<Budget> {
    const budget = await api.getBudget(id);
    upsert(budget);
    return budget;
  }

  ////////////////////////////////////////////////////////////////////
  //
  async function fetchList(params?: BudgetListParams): Promise<Budget[]> {
    loading.value = true;
    error.value = null;
    try {
      const page = await api.listBudgets(params);
      for (const b of page.results) upsert(b);
      return page.results;
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err);
      throw err;
    } finally {
      loading.value = false;
    }
  }

  ////////////////////////////////////////////////////////////////////
  //
  function clear() {
    cache.value.clear();
  }

  return {
    all,
    loading,
    error,
    byId,
    upsert,
    fetchOne,
    fetchList,
    clear,
  };
});
