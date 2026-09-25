//
// `useFundingRun`: an account's funding summary and the "Run funding
// now" action.  Feature composable (bankAccounts).
//
// A run moves money into budgets on the server, so afterwards the
// account and its budgets are refetched (the top bar's Unallocated
// balance included) along with the summary.
//

// 3rd party imports
//
import { computed, ref } from "vue";

// app imports
//
import { api } from "@/api";
import { describeError } from "@/api/errors";
import { useResource } from "@/composables/useResource";
import type { FundingRunResult } from "@/models/bankAccount";
import {
  fundingRunIsNoop,
  fundingRunResultFromDto,
  fundingSummaryFromDto,
} from "@/models/bankAccount";
import { useBankAccountsStore } from "@/stores/bankAccounts";
import { useBudgetsStore } from "@/stores/budgets";

////////////////////////////////////////////////////////////////////////
//
export function useFundingRun(accountId: () => string) {
  const accounts = useBankAccountsStore();
  const budgets = useBudgetsStore();

  const summary = useResource(accountId, async (id: string) =>
    fundingSummaryFromDto(await api.bankAccounts.fundingSummary(id)),
  );

  const running = ref(false);
  const result = ref<FundingRunResult | null>(null);
  const error = ref<string | null>(null);

  async function run(): Promise<void> {
    const id = accountId();
    running.value = true;
    result.value = null;
    error.value = null;
    try {
      result.value = fundingRunResultFromDto(await api.bankAccounts.runFunding(id));
      await Promise.all([
        accounts.fetchOne(id).catch(() => undefined),
        budgets.refreshAccount(id).catch(() => undefined),
        summary.reload(),
      ]);
    } catch (err) {
      error.value = describeError(err, "Funding run failed.");
    } finally {
      running.value = false;
    }
  }

  return {
    summary: computed(() => summary.data.value ?? null),
    nextDate: computed(() => summary.data.value?.schedules[0]?.nextDate ?? null),
    running,
    result,
    nothingDue: computed(() => !!result.value && fundingRunIsNoop(result.value)),
    error,
    run,
  };
}
