//
// `useBudgetTransactions`: the transactions allocated to one budget,
// optionally mixed with its transfers, searchable and grouped by date.
// Feature composable (budgets).
//
// The API lists allocations by budget but has no endpoint returning a
// budget's transactions, so each transaction is fetched by id (at most
// `CONCURRENCY` at a time).  A transaction only partly allocated here
// is a split; its other allocations are fetched so the row can show
// every budget.  Everything reloads when the budget id changes, and a
// response for a previous id is dropped.
//

// 3rd party imports
//
import { computed, ref, shallowRef, watch } from "vue";

// app imports
//
import { api } from "@/api";
import { useDateGroupedRows } from "@/composables/useDateGroupedRows";
import { useFuzzySearch } from "@/composables/useFuzzySearch";
import { useResource } from "@/composables/useResource";
import type { Allocation } from "@/models/allocation";
import { allocationFromDto, indexByTransaction } from "@/models/allocation";
import type { InternalTransaction } from "@/models/internalTransaction";
import { internalTransactionFromDto } from "@/models/internalTransaction";
import { listRows, rowInstant } from "@/models/listRow";
import type { Transaction } from "@/models/transaction";
import { compareNewestFirst, transactionFromDto } from "@/models/transaction";
import { useAccountContextStore } from "@/stores/accountContext";
import { useAllocationsStore } from "@/stores/allocations";
import { useBudgetsStore } from "@/stores/budgets";
import { useSessionStore } from "@/stores/session";

////////////////////////////////////////////////////////////////////////
//
const CONCURRENCY = 6;

// `fn` over `items`, at most `limit` calls in flight, results in order.
//
async function mapLimit<T, R>(items: T[], limit: number, fn: (item: T) => Promise<R>) {
  const out: R[] = new Array(items.length);
  let next = 0;
  async function worker() {
    while (next < items.length) {
      const i = next++;
      out[i] = await fn(items[i]);
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker));
  return out;
}

async function allocationsFor(query: { budget?: string; transaction?: string }) {
  const first = await api.allocations.list(query);
  return (await api.pages.all(first)).map(allocationFromDto);
}

////////////////////////////////////////////////////////////////////////
//
interface BudgetTransactions {
  transactions: Transaction[];
  allocationsByTx: Map<string, Allocation[]>;
}

async function loadBudgetTransactions(budgetId: string): Promise<BudgetTransactions> {
  const allocationsByTx = indexByTransaction(await allocationsFor({ budget: budgetId }));
  const transactions = await mapLimit([...allocationsByTx.keys()], CONCURRENCY, async (id) =>
    transactionFromDto(await api.transactions.get(id)),
  );

  const splits = transactions.filter((tx) => {
    const allocs = allocationsByTx.get(tx.id);
    return allocs?.length === 1 && !allocs[0].amount.abs().equals(tx.amount.abs());
  });
  await mapLimit(splits, CONCURRENCY, async (tx) => {
    allocationsByTx.set(tx.id, await allocationsFor({ transaction: tx.id }));
  });

  return { transactions: transactions.sort(compareNewestFirst), allocationsByTx };
}

////////////////////////////////////////////////////////////////////////
//
export function useBudgetTransactions(budgetId: () => string) {
  const session = useSessionStore();
  const ctx = useAccountContextStore();
  const budgets = useBudgetsStore();
  const allocationsStore = useAllocationsStore();

  ////////////////////////////////////////////////////////////////////
  //
  const resource = useResource(budgetId, loadBudgetTransactions);
  const transactions = shallowRef<Transaction[]>([]);
  const allocationsByTx = shallowRef(new Map<string, Allocation[]>());

  watch(resource.data, (data) => {
    transactions.value = data?.transactions ?? [];
    allocationsByTx.value = data?.allocationsByTx ?? new Map();
  });

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
  const search = useFuzzySearch(
    () => transactions.value,
    (tx) => `${tx.party ?? ""} ${tx.description} ${tx.rawDescription}`,
  );

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
  // Budget balances (this budget and Unallocated) are then refetched.
  //
  async function removeTransaction(transactionId: string): Promise<void> {
    const id = budgetId();
    try {
      const current = await allocationsFor({ transaction: transactionId });
      const splits: Record<string, string> = {};
      for (const a of current) {
        if (a.budgetId && a.budgetId !== id) splits[a.budgetId] = a.amount.abs().toDecimalString();
      }
      const updated = (await api.transactions.split(transactionId, splits)).map(allocationFromDto);

      transactions.value = transactions.value.filter((tx) => tx.id !== transactionId);
      const next = new Map(allocationsByTx.value);
      next.delete(transactionId);
      allocationsByTx.value = next;

      const accountId = ctx.activeBankAccountId;
      if (accountId) {
        allocationsStore.setForTransaction(accountId, transactionId, updated);
        await budgets.refreshAccount(accountId);
      } else {
        await budgets.fetchOne(id);
      }
    } catch {
      await resource.reload();
    }
  }

  return {
    transactions: computed(() => transactions.value),
    allocationsByTx: computed(() => allocationsByTx.value),
    loading: resource.loading,
    showTransfers: computed(() => showTransfers.value),
    toggleTransfers,
    query: search.query,
    clearSearch: search.clear,
    groups,
    removeTransaction,
  };
}
