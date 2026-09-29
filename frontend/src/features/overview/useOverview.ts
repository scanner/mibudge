//
// `useOverview`: the data behind the overview page -- the first six
// standalone budgets, the five most recent transactions with their
// allocations, and the funding summary.  Feature composable
// (overview).
//
// Reloads when the active account changes; a response for the
// previous account is ignored.
//

// 3rd party imports
//
import { computed } from "vue";

// app imports
//
import { api } from "@/api";
import { useResource } from "@/composables/useResource";
import type { FundingSummary } from "@/models/bankAccount";
import { fundingSummaryFromDto } from "@/models/bankAccount";
import type { Budget } from "@/models/budget";
import { fillupIndex } from "@/models/budget";
import type { Transaction } from "@/models/transaction";
import { transactionFromDto } from "@/models/transaction";
import { useAccountContextStore } from "@/stores/accountContext";
import { useBudgetsStore } from "@/stores/budgets";

////////////////////////////////////////////////////////////////////////
//
const BUDGET_COUNT = 6;
const RECENT_COUNT = 5;

interface Loaded {
  budgetIds: string[];
  recent: Transaction[];
  summary: FundingSummary;
}

////////////////////////////////////////////////////////////////////////
//
export function useOverview() {
  const ctx = useAccountContextStore();
  const store = useBudgetsStore();

  const resource = useResource(
    () => ctx.activeBankAccountId,
    async (accountId: string): Promise<Loaded> => {
      const [budgets, txPage, summary] = await Promise.all([
        store.fetchList({
          bank_account: accountId,
          archived: false,
          ordering: "name",
        }),
        api.transactions.list({
          bank_account: accountId,
          ordering: "-transaction_date,-created_at",
          page_size: RECENT_COUNT,
        }),
        api.bankAccounts.fundingSummary(accountId),
      ]);
      return {
        budgetIds: budgets.map((b) => b.id),
        recent: txPage.results.map(transactionFromDto),
        summary: fundingSummaryFromDto(summary),
      };
    },
    { errorMessage: "Failed to load overview." },
  );

  ////////////////////////////////////////////////////////////////////
  //
  const allBudgets = computed<Budget[]>(() =>
    (resource.data.value?.budgetIds ?? [])
      .map((id) => store.byId(id))
      .filter((b): b is Budget => !!b),
  );

  const budgets = computed(() =>
    allBudgets.value
      .filter((b) => b.budgetType !== "A" && b.id !== ctx.unallocatedBudgetId)
      .slice(0, BUDGET_COUNT),
  );

  const fillups = computed(() => fillupIndex(allBudgets.value));

  function fillupFor(budget: Budget): Budget | undefined {
    return budget.fillupGoalId
      ? fillups.value.get(budget.fillupGoalId)
      : undefined;
  }

  const unallocated = computed(() => store.byId(ctx.unallocatedBudgetId));

  return {
    budgets,
    fillupFor,
    unallocated,
    budgetNames: computed(() => store.names),
    recentTransactions: computed(() => resource.data.value?.recent ?? []),
    summary: computed(() => resource.data.value?.summary ?? null),
    loading: resource.loading,
    error: resource.error,
  };
}
