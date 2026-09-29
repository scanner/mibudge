//
// `useBudgetTransactions`: the transactions allocated to one budget,
// optionally mixed with its transfers, searchable and grouped by date.
// Feature composable (budgets).
//
// Pages come from `GET /api/v1/transactions/?budget=<id>` through
// `useInfiniteList`, each row carrying all of its allocations (a split
// shows every budget).  Everything reloads when the budget id changes,
// and a page for a previous id is dropped.  Search matches the loaded
// rows at once and asks the server for older matches after a pause
// (`useMergedSearch`).
//
// `error` is the load's failure or the last failed removal, with the
// server's message when it sent one.
//

// 3rd party imports
//
import { computed, ref, watch } from "vue";

// app imports
//
import { api } from "@/api";
import type { TransactionDto } from "@/api/dto";
import { describeError } from "@/api/errors";
import { useDateGroupedRows } from "@/composables/useDateGroupedRows";
import { useInfiniteList } from "@/composables/useInfiniteList";
import { useMergedSearch } from "@/composables/useMergedSearch";
import { useResource } from "@/composables/useResource";
import type { InternalTransaction } from "@/models/internalTransaction";
import { internalTransactionFromDto } from "@/models/internalTransaction";
import { listRows, rowInstant } from "@/models/listRow";
import { pageFromDto } from "@/models/page";
import type { Transaction } from "@/models/transaction";
import { transactionFromDto } from "@/models/transaction";
import { useAccountContextStore } from "@/stores/accountContext";
import { useBudgetsStore } from "@/stores/budgets";
import { useSessionStore } from "@/stores/session";

////////////////////////////////////////////////////////////////////////
//
const ORDERING = "-transaction_date,-created_at";

function searchText(tx: Transaction): string {
  return `${tx.party ?? ""} ${tx.description} ${tx.rawDescription}`;
}

////////////////////////////////////////////////////////////////////////
//
export function useBudgetTransactions(budgetId: () => string) {
  const session = useSessionStore();
  const ctx = useAccountContextStore();
  const budgets = useBudgetsStore();

  ////////////////////////////////////////////////////////////////////
  //
  const list = useInfiniteList(
    async () =>
      pageFromDto(
        await api.transactions.list({ budget: budgetId(), ordering: ORDERING }),
        transactionFromDto,
      ),
    async (url) =>
      pageFromDto(
        await api.pages.fetchPage<TransactionDto>(url),
        transactionFromDto,
      ),
    { errorMessage: "Failed to load this budget's transactions." },
  );

  // Transactions taken off this budget since the list loaded.
  const removedIds = ref(new Set<string>());
  const transactions = computed(() =>
    list.items.value.filter((tx) => !removedIds.value.has(tx.id)),
  );
  const actionError = ref<string | null>(null);

  function reload(): void {
    removedIds.value = new Set();
    actionError.value = null;
    void list.reload();
  }

  watch(budgetId, reload, { immediate: true });

  ////////////////////////////////////////////////////////////////////
  //
  // Transfers in and out of the budget, loaded the first time they are
  // shown.
  //
  const showTransfers = ref(false);
  const transfers = useResource(
    () => (showTransfers.value ? budgetId() : null),
    async (id: string): Promise<InternalTransaction[]> => {
      const first = await api.internalTransactions.list({ budget: id });
      return (await api.pages.all(first)).map(internalTransactionFromDto);
    },
  );

  function toggleTransfers(): void {
    showTransfers.value = !showTransfers.value;
  }

  ////////////////////////////////////////////////////////////////////
  //
  const search = useMergedSearch({
    items: () => transactions.value,
    text: searchText,
    id: (tx) => tx.id,
    scope: budgetId,
    fetchMatches: async (q) =>
      (
        await api.transactions.list({
          budget: budgetId(),
          search: q,
          ordering: ORDERING,
        })
      ).results.map(transactionFromDto),
    refine: (txs) => txs.filter((tx) => !removedIds.value.has(tx.id)),
  });

  const groups = useDateGroupedRows(
    () =>
      listRows(
        search.results.value ?? transactions.value,
        showTransfers.value ? (transfers.data.value ?? []) : null,
      ),
    { instantOf: rowInstant, timezone: () => session.timezone },
  );

  ////////////////////////////////////////////////////////////////////
  //
  // Take this budget's allocation off a transaction: the remaining
  // assigned amounts are re-declared and the rest goes to Unallocated.
  // Budget balances (this budget and Unallocated) are then refetched;
  // that refetch failing leaves the cached balances, since the removal
  // itself succeeded.  A failed removal reloads the list, so it shows
  // what the server has.
  //
  async function removeTransaction(transactionId: string): Promise<void> {
    const id = budgetId();
    actionError.value = null;
    try {
      const current = transactionFromDto(
        await api.transactions.get(transactionId),
      );
      const splits: Record<string, string> = {};
      for (const a of current.allocations) {
        if (a.budgetId && a.budgetId !== id)
          splits[a.budgetId] = a.amount.abs().toDecimalString();
      }
      await api.transactions.split(transactionId, splits);
    } catch (err) {
      if (budgetId() === id) {
        actionError.value = describeError(
          err,
          "Couldn't remove the transaction from this budget.",
        );
        removedIds.value = new Set();
        await list.reload();
      }
      return;
    }

    if (budgetId() === id)
      removedIds.value = new Set([...removedIds.value, transactionId]);
    const accountId = ctx.activeBankAccountId;
    if (accountId) {
      await budgets.refreshAccount(accountId).catch(() => undefined);
    } else {
      await budgets.fetchOne(id).catch(() => undefined);
    }
  }

  return {
    transactions,
    loading: list.loading,
    loadingMore: list.loadingMore,
    loadMoreError: list.loadMoreError,
    loadMore: list.loadMore,
    sentinel: list.sentinel,
    error: computed(() => actionError.value ?? list.error.value),
    showTransfers: computed(() => showTransfers.value),
    toggleTransfers,
    query: search.query,
    clearSearch: search.clear,
    groups,
    removeTransaction,
  };
}
