//
// `useBudgetDetail`: one budget, its fill-up goal, and the pause /
// archive actions.  Feature composable (budgets).
//
// The budget is loaded through the budgets store and read back from
// it, so every change made anywhere (a transfer, an edit, a split)
// shows here without reloading.  The load follows the `id` getter: a
// route reused with a new id loads the new budget, and a response for
// the previous id is ignored.
//

// 3rd party imports
//
import { computed, ref } from "vue";

// app imports
//
import { describeError } from "@/api/errors";
import { useResource } from "@/composables/useResource";
import { useAccountContextStore } from "@/stores/accountContext";
import { useBudgetsStore } from "@/stores/budgets";

////////////////////////////////////////////////////////////////////////
//
export function useBudgetDetail(id: () => string) {
  const store = useBudgetsStore();
  const ctx = useAccountContextStore();
  const actionError = ref<string | null>(null);

  ////////////////////////////////////////////////////////////////////
  //
  const resource = useResource(
    id,
    async (budgetId: string) => {
      actionError.value = null;
      const budget = await store.fetchOne(budgetId);
      if (budget.fillupGoalId) await store.fetchOne(budget.fillupGoalId);
      return budgetId;
    },
    { errorMessage: "Failed to load budget." },
  );

  const budget = computed(() => store.byId(resource.data.value));
  const fillupBudget = computed(() => store.byId(budget.value?.fillupGoalId));
  const isUnallocated = computed(
    () => !!budget.value && budget.value.id === ctx.unallocatedBudgetId,
  );
  const accountName = computed(() => ctx.activeBankAccount?.name);

  ////////////////////////////////////////////////////////////////////
  //
  async function togglePause(): Promise<void> {
    const b = budget.value;
    if (!b) return;
    actionError.value = null;
    try {
      await store.update(b.id, { paused: !b.paused });
    } catch (err) {
      actionError.value = describeError(err, "Failed to update budget.");
    }
  }

  // Resolves `true` once archived.
  //
  async function archive(): Promise<boolean> {
    const b = budget.value;
    if (!b) return false;
    actionError.value = null;
    try {
      await store.archive(b.id);
      return true;
    } catch (err) {
      actionError.value = describeError(err, "Failed to archive budget.");
      return false;
    }
  }

  return {
    budget,
    fillupBudget,
    isUnallocated,
    accountName,
    loading: resource.loading,
    error: resource.error,
    actionError,
    reload: resource.reload,
    togglePause,
    archive,
  };
}
