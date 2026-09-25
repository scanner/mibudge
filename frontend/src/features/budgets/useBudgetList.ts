//
// `useBudgetList`: an account's non-archived budgets (by name) and its
// funding summary.  Feature composable (budgets).
//
// Budgets are fetched through the budgets store and read back from it,
// so edits made elsewhere show without reloading.  Reloads when the
// account changes; a response for the previous account is ignored.
//

// 3rd party imports
//
import { computed } from "vue";

// app imports
//
import { api } from "@/api";
import { useResource } from "@/composables/useResource";
import type { Budget } from "@/models/budget";
import { fillupIndex } from "@/models/budget";
import type { FundingSummary } from "@/models/bankAccount";
import { fundingSummaryFromDto } from "@/models/bankAccount";
import { useBudgetsStore } from "@/stores/budgets";

////////////////////////////////////////////////////////////////////////
//
interface Loaded {
  ids: string[];
  summary: FundingSummary;
}

////////////////////////////////////////////////////////////////////////
//
export function useBudgetList(accountId: () => string | null) {
  const store = useBudgetsStore();

  const resource = useResource(
    accountId,
    async (id: string): Promise<Loaded> => {
      const [budgets, summary] = await Promise.all([
        store.fetchList({
          bank_account: id,
          archived: false,
          ordering: "name",
        }),
        api.bankAccounts.fundingSummary(id),
      ]);
      return {
        ids: budgets.map((b) => b.id),
        summary: fundingSummaryFromDto(summary),
      };
    },
    { errorMessage: "Failed to load budgets." },
  );

  // Includes fill-up goals (type `A`); callers attach them to their
  // parents with `fillupFor` and filter them out of the list.
  //
  const budgets = computed<Budget[]>(() =>
    (resource.data.value?.ids ?? [])
      .map((id) => store.byId(id))
      .filter((b): b is Budget => !!b && !b.archived),
  );

  const fillups = computed(() => fillupIndex(budgets.value));

  function fillupFor(budget: Budget): Budget | undefined {
    return budget.fillupGoalId
      ? fillups.value.get(budget.fillupGoalId)
      : undefined;
  }

  return {
    budgets,
    fillupFor,
    summary: computed(() => resource.data.value?.summary ?? null),
    loading: resource.loading,
    error: resource.error,
    reload: resource.reload,
  };
}
