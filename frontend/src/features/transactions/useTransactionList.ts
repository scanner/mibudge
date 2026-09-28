//
// `useTransactionList`: the active account's transactions with filter
// chips, search, optional transfers, date grouping and infinite scroll.
// Feature composable (transactions).
//
// - Pages come from `useInfiniteList`, each row carrying its
//   allocations.  Every visit, account switch, and change into or out
//   of the Unallocated filter reloads; a page that arrives for the
//   previous account or filter is dropped.
// - The Unallocated filter is a server query (`unallocated=true`), so
//   it covers the whole history.  Pending and Income filter the loaded
//   rows.
// - Search matches the loaded (filtered) rows at once and asks the
//   server for older matches after a pause (`useMergedSearch`).
// - The transaction-nav store receives the ids of the rows on screen,
//   in display order, so the detail view's previous / next follow the
//   active filter and search.  The filter and search themselves are
//   kept there across a visit to the detail view.
//

// 3rd party imports
//
import { computed, nextTick, ref, watch } from "vue";

// app imports
//
import { api } from "@/api";
import type { TransactionDto } from "@/api/dto";
import { useDateGroupedRows } from "@/composables/useDateGroupedRows";
import { useInfiniteList } from "@/composables/useInfiniteList";
import { useMergedSearch } from "@/composables/useMergedSearch";
import { useResource } from "@/composables/useResource";
import { isUnallocated } from "@/models/allocation";
import { internalTransactionFromDto } from "@/models/internalTransaction";
import type { InternalTransaction } from "@/models/internalTransaction";
import { listRows, rowInstant } from "@/models/listRow";
import { pageFromDto } from "@/models/page";
import type { Transaction } from "@/models/transaction";
import { transactionFromDto } from "@/models/transaction";
import { useAccountContextStore } from "@/stores/accountContext";
import { useBudgetsStore } from "@/stores/budgets";
import { useSessionStore } from "@/stores/session";
import { useTransactionNavStore } from "@/stores/transactionNav";

////////////////////////////////////////////////////////////////////////
//
export type TransactionFilter = "all" | "unallocated" | "pending" | "income";

export const FILTER_CHIPS: { key: TransactionFilter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "unallocated", label: "Unallocated" },
  { key: "pending", label: "Pending" },
  { key: "income", label: "Income" },
];

const ORDERING = "-transaction_date,-created_at";

function searchText(tx: Transaction): string {
  return `${tx.party ?? ""} ${tx.description} ${tx.rawDescription}`;
}

////////////////////////////////////////////////////////////////////////
//
export function useTransactionList() {
  const session = useSessionStore();
  const ctx = useAccountContextStore();
  const budgets = useBudgetsStore();
  const nav = useTransactionNavStore();

  const accountId = computed(() => ctx.activeBankAccountId);

  ////////////////////////////////////////////////////////////////////
  //
  const activeFilter = ref<TransactionFilter>(
    (nav.savedFilter as TransactionFilter) || "all",
  );

  // The list query for the active account and filter.
  //
  function listQuery(extra: { search?: string } = {}) {
    return {
      bank_account: accountId.value!,
      ordering: ORDERING,
      ...(activeFilter.value === "unallocated" ? { unallocated: true } : {}),
      ...extra,
    };
  }

  ////////////////////////////////////////////////////////////////////
  //
  const list = useInfiniteList(
    async () =>
      pageFromDto(await api.transactions.list(listQuery()), transactionFromDto),
    async (url) =>
      pageFromDto(
        await api.pages.fetchPage<TransactionDto>(url),
        transactionFromDto,
      ),
    { errorMessage: "Failed to load transactions." },
  );

  // The server applies the Unallocated filter; checking the embedded
  // allocations here as well keeps rows the server matched before a
  // split in this tab from showing.
  //
  function applyFilter(txs: readonly Transaction[]): Transaction[] {
    switch (activeFilter.value) {
      case "unallocated":
        return txs.filter((tx) =>
          isUnallocated(tx.allocations, ctx.unallocatedBudgetId),
        );
      case "pending":
        return txs.filter((tx) => tx.pending);
      case "income":
        return txs.filter((tx) => tx.amount.isPositive());
      default:
        return [...txs];
    }
  }

  const filtered = computed(() => applyFilter(list.items.value));

  ////////////////////////////////////////////////////////////////////
  //
  // Search: local matches over the filtered rows, plus older matches
  // from the server under the same account and filter.
  //
  const search = useMergedSearch({
    items: () => filtered.value,
    text: searchText,
    id: (tx) => tx.id,
    scope: () =>
      accountId.value ? `${accountId.value}:${activeFilter.value}` : null,
    fetchMatches: async (q) =>
      (await api.transactions.list(listQuery({ search: q }))).results.map(
        transactionFromDto,
      ),
    refine: applyFilter,
    initialQuery: nav.savedSearch,
  });

  ////////////////////////////////////////////////////////////////////
  //
  // Transfers, loaded the first time they are shown for an account.
  //
  const showTransfers = ref(false);
  const transfers = useResource(
    () => (showTransfers.value ? accountId.value : null),
    async (id: string): Promise<InternalTransaction[]> => {
      const first = await api.internalTransactions.list({ bank_account: id });
      return (await api.pages.all(first)).map(internalTransactionFromDto);
    },
  );

  function toggleTransfers(): void {
    showTransfers.value = !showTransfers.value;
  }

  ////////////////////////////////////////////////////////////////////
  //
  const groups = useDateGroupedRows(
    () =>
      listRows(
        search.results.value ?? filtered.value,
        showTransfers.value ? (transfers.data.value ?? []) : null,
      ),
    { instantOf: rowInstant, timezone: () => session.timezone },
  );

  // The transaction rows on screen, in display order.
  const visibleIds = computed(() =>
    groups.value.flatMap((g) =>
      g.rows.flatMap((r) => (r.kind === "tx" ? [r.tx.id] : [])),
    ),
  );

  ////////////////////////////////////////////////////////////////////
  //
  function reload(): void {
    const id = accountId.value;
    if (!id) {
      list.clear();
      return;
    }
    void list.reload();
    // Budget names for the rows; a failure leaves the cached names.
    void budgets.refreshAccount(id).catch(() => undefined);
  }

  watch(accountId, reload, { immediate: true });
  watch(visibleIds, (ids) => nav.setIds(ids), { immediate: true });
  watch(search.query, (q) => (nav.savedSearch = q));
  watch(activeFilter, (f, old) => {
    nav.savedFilter = f;
    if ((f === "unallocated") !== (old === "unallocated")) {
      reload();
      return;
    }
    // A narrower filter can leave the scroll sentinel on screen with
    // nothing left to scroll; keep loading until it is off screen.
    void nextTick(() => list.loadMore());
  });

  return {
    groups,
    loading: list.loading,
    loadingMore: list.loadingMore,
    loadMoreError: list.loadMoreError,
    loadMore: list.loadMore,
    error: list.error,
    sentinel: list.sentinel,
    activeFilter,
    query: search.query,
    clearSearch: search.clear,
    showTransfers: computed(() => showTransfers.value),
    toggleTransfers,
    reload,
  };
}
