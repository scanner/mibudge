//
// `useTransactionList`: the active account's transactions with filter
// chips, search, optional transfers, date grouping and infinite scroll.
// Feature composable (transactions).
//
// - Pages come from `useInfiniteList`; switching accounts reloads, and
//   a page that arrives for the previous account is dropped.
// - Each row's allocations come from the allocations store.  Every
//   visit (and account switch) refetches the account's index, since a
//   sync or a co-owner may have changed it; the cached index stays on
//   screen until the new one lands.  With no index cached yet the list
//   shows as loading, so the Unallocated filter never guesses.
// - Search matches the loaded (filtered) rows at once and asks the
//   server for older matches after a pause; server matches are merged
//   in when the query and account are unchanged.
// - The transaction-nav store receives the ids of the rows on screen,
//   in display order, so the detail view's previous / next follow the
//   active filter and search.  The filter and search themselves are
//   kept there across a visit to the detail view.
//

// 3rd party imports
//
import {
  computed,
  getCurrentScope,
  nextTick,
  onScopeDispose,
  ref,
  shallowRef,
  watch,
} from "vue";

// app imports
//
import { api } from "@/api";
import type { TransactionDto } from "@/api/dto";
import { useDateGroupedRows } from "@/composables/useDateGroupedRows";
import { useFuzzySearch } from "@/composables/useFuzzySearch";
import { useInfiniteList } from "@/composables/useInfiniteList";
import { useAsync } from "@/composables/useAsync";
import { useResource } from "@/composables/useResource";
import { addDays, todayDateStr, txDateStr } from "@/domain/dates";
import { isUnallocated } from "@/models/allocation";
import { internalTransactionFromDto } from "@/models/internalTransaction";
import type { InternalTransaction } from "@/models/internalTransaction";
import { listRows, rowInstant } from "@/models/listRow";
import { pageFromDto } from "@/models/page";
import type { Transaction } from "@/models/transaction";
import { occurredAt, transactionFromDto } from "@/models/transaction";
import { useAccountContextStore } from "@/stores/accountContext";
import { useAllocationsStore } from "@/stores/allocations";
import { useBudgetsStore } from "@/stores/budgets";
import { useSessionStore } from "@/stores/session";
import { useTransactionNavStore } from "@/stores/transactionNav";

////////////////////////////////////////////////////////////////////////
//
export type TransactionFilter =
  | "all"
  | "unallocated"
  | "pending"
  | "income"
  | "last30";

export const FILTER_CHIPS: { key: TransactionFilter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "unallocated", label: "Unallocated" },
  { key: "pending", label: "Pending" },
  { key: "income", label: "Income" },
  { key: "last30", label: "Last 30 days" },
];

const ORDERING = "-transaction_date,-created_at";
const SERVER_SEARCH_DELAY_MS = 300;

function searchText(tx: Transaction): string {
  return `${tx.party ?? ""} ${tx.description} ${tx.rawDescription}`;
}

////////////////////////////////////////////////////////////////////////
//
export function useTransactionList() {
  const session = useSessionStore();
  const ctx = useAccountContextStore();
  const budgets = useBudgetsStore();
  const allocations = useAllocationsStore();
  const nav = useTransactionNavStore();

  const accountId = computed(() => ctx.activeBankAccountId);

  ////////////////////////////////////////////////////////////////////
  //
  const list = useInfiniteList(
    async () =>
      pageFromDto(
        await api.transactions.list({
          bank_account: accountId.value!,
          ordering: ORDERING,
        }),
        transactionFromDto,
      ),
    async (url) =>
      pageFromDto(
        await api.pages.fetchPage<TransactionDto>(url),
        transactionFromDto,
      ),
    { errorMessage: "Failed to load transactions." },
  );

  const allocationsByTx = computed(() =>
    accountId.value ? allocations.indexFor(accountId.value) : null,
  );

  // The index refetch; its `error` is the server's message.  A failed
  // refetch is reported beside the list, which still shows the loaded
  // transactions.
  const indexLoad = useAsync(
    (id: string) => allocations.loadForAccount(id, true),
    {
      errorMessage: "Failed to load budget assignments.",
    },
  );
  const awaitingIndex = computed(
    () => !!accountId.value && !allocationsByTx.value && !indexLoad.error.value,
  );

  ////////////////////////////////////////////////////////////////////
  //
  const activeFilter = ref<TransactionFilter>(
    (nav.savedFilter as TransactionFilter) || "all",
  );

  function applyFilter(txs: readonly Transaction[]): Transaction[] {
    const unallocId = ctx.unallocatedBudgetId;
    switch (activeFilter.value) {
      case "unallocated": {
        const index = allocationsByTx.value;
        if (!index) return [];
        // A transaction the index has not seen is newer than the index
        // (a sync since it loaded); new transactions start unassigned.
        return txs.filter((tx) =>
          isUnallocated(index.get(tx.id) ?? [], unallocId),
        );
      }
      case "pending":
        return txs.filter((tx) => tx.pending);
      case "income":
        return txs.filter((tx) => tx.amount.isPositive());
      case "last30": {
        const tz = session.timezone;
        const cutoff = addDays(todayDateStr(tz), -30);
        return txs.filter((tx) => txDateStr(occurredAt(tx), tz) >= cutoff);
      }
      default:
        return [...txs];
    }
  }

  const filtered = computed(() => applyFilter(list.items.value));

  ////////////////////////////////////////////////////////////////////
  //
  // Search: local matches over the filtered rows, plus older matches
  // from the server.
  //
  const local = useFuzzySearch(() => filtered.value, searchText, {
    initialQuery: nav.savedSearch,
  });
  const serverMatches = shallowRef<Transaction[]>([]);
  let serverTimer: ReturnType<typeof setTimeout> | null = null;
  let serverGeneration = 0;

  watch(
    [() => local.query.value.trim(), accountId],
    ([q, account]) => {
      const current = ++serverGeneration;
      if (serverTimer) clearTimeout(serverTimer);
      serverMatches.value = [];
      if (!q || !account) return;
      serverTimer = setTimeout(async () => {
        try {
          const page = await api.transactions.list({
            bank_account: account,
            search: q,
            ordering: ORDERING,
          });
          if (current === serverGeneration) {
            serverMatches.value = page.results.map(transactionFromDto);
          }
        } catch {
          // Server search is best-effort; local matches still show.
        }
      }, SERVER_SEARCH_DELAY_MS);
    },
    { immediate: true },
  );
  if (getCurrentScope()) {
    onScopeDispose(() => {
      serverGeneration++;
      if (serverTimer) clearTimeout(serverTimer);
    });
  }

  const searchResults = computed<Transaction[] | null>(() => {
    const localResults = local.results.value;
    if (!localResults) return null;
    const seen = new Set(localResults.map((tx) => tx.id));
    const extra = applyFilter(serverMatches.value).filter(
      (tx) => !seen.has(tx.id),
    );
    return [...localResults, ...extra];
  });

  function clearSearch(): void {
    local.clear();
  }

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
        searchResults.value ?? filtered.value,
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
    void indexLoad.run(id);
    // Budget names for the rows; a failure leaves the cached names.
    void budgets.refreshAccount(id).catch(() => undefined);
  }

  watch(accountId, reload, { immediate: true });
  watch(visibleIds, (ids) => nav.setIds(ids), { immediate: true });
  watch(local.query, (q) => (nav.savedSearch = q));
  watch(activeFilter, (f) => {
    nav.savedFilter = f;
    // A narrower filter can leave the scroll sentinel on screen with
    // nothing left to scroll; keep loading until it is off screen.
    void nextTick(() => list.loadMore());
  });

  return {
    groups,
    allocationsByTx,
    loading: computed(() => list.loading.value || awaitingIndex.value),
    loadingMore: list.loadingMore,
    loadMoreError: list.loadMoreError,
    loadMore: list.loadMore,
    error: list.error,
    assignmentsError: indexLoad.error,
    sentinel: list.sentinel,
    activeFilter,
    query: local.query,
    clearSearch,
    showTransfers: computed(() => showTransfers.value),
    toggleTransfers,
    reload,
  };
}
