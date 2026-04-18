<script setup lang="ts">
//
// TransactionsView — transaction list with filter chips, date-grouped
// rows, infinite scroll, and fzf fuzzy search.  (UI_SPEC §4.5)
//
// Data flow:
//   1. Fetch first page of transactions for the active bank account.
//   2. Batch-fetch all allocations for the same account (single call).
//   3. Build a Map<transactionId, TransactionAllocation[]> for lookup.
//   4. Budget names come from the budgets store cache.
//
// Search: client-side fzf (150ms debounce) over loaded transactions,
// with server-side fallback (300ms debounce) for deep history.
//

// 3rd party imports
//
import { Fzf } from "fzf";
import { IconSearch, IconX } from "@tabler/icons-vue";
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";

// app imports
//
import AppShell from "@/components/layout/AppShell.vue";
import EmptyState from "@/components/shared/EmptyState.vue";
import TransactionRow from "@/components/transactions/TransactionRow.vue";
import { listAllocations } from "@/api/allocations";
import { listTransactions, listTransactionsNext } from "@/api/transactions";
import { fetchAllPages } from "@/api/util";
import { useAccountContextStore } from "@/stores/accountContext";
import { useBudgetsStore } from "@/stores/budgets";
import { useTransactionNavStore } from "@/stores/transactionNav";
import type { Transaction, TransactionAllocation } from "@/types/api";

////////////////////////////////////////////////////////////////////////
//
const ctx = useAccountContextStore();
const txNav = useTransactionNavStore();
const budgets = useBudgetsStore();

////////////////////////////////////////////////////////////////////////
//
// Filter chips — each maps to API params or a client-side predicate.
//
type Filter = "all" | "unallocated" | "pending" | "income" | "last30";
const activeFilter = ref<Filter>((txNav.savedFilter as Filter) || "all");

const filterChips: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "unallocated", label: "Unallocated" },
  { key: "pending", label: "Pending" },
  { key: "income", label: "Income" },
  { key: "last30", label: "Last 30 days" },
];

////////////////////////////////////////////////////////////////////////
//
// Core state.
//
const transactions = ref<Transaction[]>([]);
const nextPageUrl = ref<string | null>(null);
const allocsByTx = ref(new Map<string, TransactionAllocation[]>());
const loading = ref(false);
const loadingMore = ref(false);
const error = ref<string | null>(null);

////////////////////////////////////////////////////////////////////////
//
// Search state.
//
const searchOpen = ref(!!txNav.savedSearch);
const searchQuery = ref(txNav.savedSearch);
const searchResults = ref<Transaction[] | null>(null);
let fzfDebounce: ReturnType<typeof setTimeout> | null = null;
let serverDebounce: ReturnType<typeof setTimeout> | null = null;

////////////////////////////////////////////////////////////////////////
//
// Budget name lookup for TransactionRow.
//
const budgetNames = computed(() => {
  const map = new Map<string, string>();
  for (const b of budgets.all) {
    map.set(b.id, b.name);
  }
  return map;
});

////////////////////////////////////////////////////////////////////////
//
// Date-grouped transaction list.
//
interface DateGroup {
  date: string;
  label: string;
  transactions: Transaction[];
}

function formatDateHeader(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);

  if (d.getTime() === today.getTime()) return "Today";
  if (d.getTime() === yesterday.getTime()) return "Yesterday";

  return d.toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

const displayTransactions = computed(() => {
  const source = searchResults.value ?? filteredTransactions.value;
  const map = new Map<string, DateGroup>();
  for (const tx of source) {
    const date = tx.transaction_date.slice(0, 10);
    let group = map.get(date);
    if (!group) {
      group = { date, label: formatDateHeader(date), transactions: [] };
      map.set(date, group);
    }
    group.transactions.push(tx);
  }
  return Array.from(map.values()).sort((a, b) => (a.date > b.date ? -1 : 1));
});

////////////////////////////////////////////////////////////////////////
//
// Client-side filtering (applied after fetch, before grouping).
//
const filteredTransactions = computed(() => {
  const list = transactions.value;
  const unallocId = ctx.unallocatedBudgetId;
  switch (activeFilter.value) {
    case "unallocated":
      return list.filter((tx) => {
        const allocs = allocsByTx.value.get(tx.id);
        if (!allocs || allocs.length === 0) return true;
        return allocs.every((a) => a.budget === unallocId || a.budget === null);
      });
    case "pending":
      return list.filter((tx) => tx.pending);
    case "income":
      return list.filter((tx) => Number.parseFloat(tx.amount) > 0);
    case "last30": {
      const cutoff = new Date();
      cutoff.setDate(cutoff.getDate() - 30);
      const cutoffStr = cutoff.toISOString().slice(0, 10);
      return list.filter((tx) => tx.transaction_date.slice(0, 10) >= cutoffStr);
    }
    default:
      return list;
  }
});

////////////////////////////////////////////////////////////////////////
//
// Data loading.
//
async function loadTransactions() {
  const accountId = ctx.activeBankAccountId;
  if (!accountId) return;

  loading.value = true;
  error.value = null;
  try {
    const [txPage, allocFirstPage, _budgets] = await Promise.all([
      listTransactions({
        bank_account: accountId,
        ordering: "-transaction_date",
      }),
      listAllocations({ bank_account: accountId }),
      budgets.fetchList({ bank_account: accountId }),
    ]);

    transactions.value = txPage.results;
    nextPageUrl.value = txPage.next;

    const allAllocs = await fetchAllPages(allocFirstPage);
    indexAllocations(allAllocs);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Failed to load transactions.";
  } finally {
    loading.value = false;
  }
}

function indexAllocations(allocs: TransactionAllocation[]) {
  const map = new Map<string, TransactionAllocation[]>();
  for (const a of allocs) {
    const list = map.get(a.transaction) ?? [];
    list.push(a);
    map.set(a.transaction, list);
  }
  allocsByTx.value = map;
}

async function loadMore() {
  if (!nextPageUrl.value || loadingMore.value) return;
  loadingMore.value = true;
  try {
    const page = await listTransactionsNext(nextPageUrl.value);
    transactions.value = [...transactions.value, ...page.results];
    nextPageUrl.value = page.next;
  } catch {
    // Silently ignore — user can scroll again to retry.
  } finally {
    loadingMore.value = false;
  }
}

////////////////////////////////////////////////////////////////////////
//
// Infinite scroll via IntersectionObserver on a sentinel element.
//
const sentinel = ref<HTMLElement | null>(null);
let observer: IntersectionObserver | null = null;

function setupObserver() {
  if (observer) observer.disconnect();
  observer = new IntersectionObserver(
    (entries) => {
      if (entries[0]?.isIntersecting && nextPageUrl.value) {
        loadMore();
      }
    },
    { rootMargin: "200px" },
  );
  if (sentinel.value) observer.observe(sentinel.value);
}

onMounted(() => {
  nextTick(setupObserver);
});

onUnmounted(() => {
  observer?.disconnect();
});

////////////////////////////////////////////////////////////////////////
//
// Search — fzf client-side (150ms) + server fallback (300ms).
//
function onSearchInput() {
  const q = searchQuery.value.trim();
  if (!q) {
    searchResults.value = null;
    return;
  }

  // Client-side fzf search over loaded transactions.
  if (fzfDebounce) clearTimeout(fzfDebounce);
  fzfDebounce = setTimeout(() => {
    const fzf = new Fzf(transactions.value, {
      selector: (tx: Transaction) => `${tx.party ?? ""} ${tx.description} ${tx.raw_description}`,
      casing: "case-insensitive",
      fuzzy: false,
    });
    const results = fzf.find(q);
    searchResults.value = results.map((r) => r.item);
  }, 150);

  // Server-side search for transactions not yet loaded.
  if (serverDebounce) clearTimeout(serverDebounce);
  serverDebounce = setTimeout(async () => {
    const accountId = ctx.activeBankAccountId;
    if (!accountId) return;
    try {
      const page = await listTransactions({
        bank_account: accountId,
        search: q,
        ordering: "-transaction_date",
      });
      // Merge server results with local fzf results, deduplicating.
      const localIds = new Set((searchResults.value ?? []).map((tx) => tx.id));
      const newFromServer = page.results.filter((tx) => !localIds.has(tx.id));
      if (newFromServer.length > 0 && searchQuery.value.trim() === q) {
        searchResults.value = [...(searchResults.value ?? []), ...newFromServer];
      }
    } catch {
      // Server search is best-effort.
    }
  }, 300);
}

function toggleSearch() {
  searchOpen.value = !searchOpen.value;
  if (!searchOpen.value) {
    searchQuery.value = "";
    searchResults.value = null;
    txNav.savedSearch = "";
  }
}

////////////////////////////////////////////////////////////////////////
//
// Persist search/filter state so it survives navigating to detail and back.
//
watch(searchQuery, (q) => {
  txNav.savedSearch = q;
});
watch(activeFilter, (f) => {
  txNav.savedFilter = f;
});

////////////////////////////////////////////////////////////////////////
//
// Watch account changes and re-setup observer when sentinel remounts.
//
watch(() => ctx.activeBankAccountId, loadTransactions, { immediate: true });

// Re-run search after data loads if there's a restored query.
watch(transactions, (txs) => {
  txNav.setIds(txs.map((t) => t.id));
  if (searchQuery.value.trim() && txs.length > 0 && !searchResults.value) {
    onSearchInput();
  }
});

watch(sentinel, (el) => {
  if (el && observer) observer.observe(el);
});
</script>

<template>
  <AppShell>
    <template #action>
      <button
        type="button"
        class="flex h-10 w-10 items-center justify-center rounded-full text-neutral-700 hover:bg-neutral-100"
        aria-label="Search transactions"
        @click="toggleSearch"
      >
        <IconSearch v-if="!searchOpen" class="h-5 w-5" />
        <IconX v-else class="h-5 w-5" />
      </button>
    </template>

    <!-- Search bar -->
    <Transition
      enter-active-class="transition-all duration-200 ease-out"
      enter-from-class="max-h-0 opacity-0"
      enter-to-class="max-h-12 opacity-100"
      leave-active-class="transition-all duration-150 ease-in"
      leave-from-class="max-h-12 opacity-100"
      leave-to-class="max-h-0 opacity-0"
    >
      <div v-if="searchOpen" class="-mx-4 overflow-hidden px-4 pb-3">
        <input
          v-model="searchQuery"
          type="text"
          placeholder="Search transactions…"
          class="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-900 outline-none transition-colors placeholder:text-neutral-400 focus:border-ocean-400 focus:ring-1 focus:ring-ocean-400"
          @input="onSearchInput"
        />
      </div>
    </Transition>

    <!-- Filter chips -->
    <div class="-mx-4 mb-4 flex gap-2 overflow-x-auto px-4 pt-1 scrollbar-none">
      <button
        v-for="chip in filterChips"
        :key="chip.key"
        type="button"
        class="flex-none rounded-full border px-3 py-1 text-xs font-medium transition-colors"
        :class="
          activeFilter === chip.key
            ? 'border-ocean-400 bg-ocean-50 text-ocean-600'
            : 'border-neutral-200 bg-white text-neutral-600 hover:border-neutral-300'
        "
        @click="activeFilter = chip.key"
      >
        {{ chip.label }}
      </button>
    </div>

    <!-- Loading skeletons -->
    <div v-if="loading" class="space-y-3">
      <div v-for="i in 6" :key="i" class="h-16 animate-pulse rounded-card bg-neutral-100" />
    </div>

    <!-- Error -->
    <div v-else-if="error" class="rounded-card bg-coral-50 px-4 py-3 text-sm text-coral-600">
      {{ error }}
    </div>

    <!-- Transaction list -->
    <template v-else>
      <div v-if="displayTransactions.length > 0" class="space-y-4">
        <section v-for="group in displayTransactions" :key="group.date">
          <h2
            class="sticky top-0 z-10 -mx-4 bg-neutral-50/95 px-4 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-neutral-500 backdrop-blur-sm"
          >
            {{ group.label }}
          </h2>
          <div class="space-y-2">
            <TransactionRow
              v-for="tx in group.transactions"
              :key="tx.id"
              :transaction="tx"
              :allocations="allocsByTx.get(tx.id)"
              :budget-names="budgetNames"
              :unallocated-budget-id="ctx.unallocatedBudgetId"
            />
          </div>
        </section>
      </div>

      <EmptyState
        v-else
        :title="searchQuery ? 'No matching transactions' : 'No transactions'"
        :message="
          searchQuery
            ? 'Try a different search term.'
            : 'Transactions will appear here once imported.'
        "
      />

      <!-- Infinite scroll sentinel -->
      <div ref="sentinel" class="h-px" />

      <!-- Loading more indicator -->
      <div v-if="loadingMore" class="flex justify-center py-4">
        <div
          class="h-5 w-5 animate-spin rounded-full border-2 border-neutral-300 border-t-ocean-400"
        />
      </div>
    </template>
  </AppShell>
</template>
