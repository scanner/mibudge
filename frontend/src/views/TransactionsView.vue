<script setup lang="ts">
//
// TransactionsView — transaction list with filter chips, date-grouped
// rows, infinite scroll, and search.  (UI_SPEC §4.5)  Route shell over
// `useTransactionList`; Cmd/Ctrl-F opens the search.
//

// 3rd party imports
//
import { IconArrowsRightLeft, IconSearch, IconX } from "@tabler/icons-vue";
import { ref } from "vue";
import { useRouter } from "vue-router";

// app imports
//
import EmptyState from "@/components/shared/EmptyState.vue";
import TransactionGroupList from "@/components/transactions/TransactionGroupList.vue";
import { useFindShortcut } from "@/composables/useFindShortcut";
import { FILTER_CHIPS as filterChips } from "@/features/transactions/useTransactionList";
import { useTransactionList } from "@/features/transactions/useTransactionList";
import AppShell from "@/features/shell/AppShell.vue";
import { useAccountContextStore } from "@/stores/accountContext";
import { useBudgetsStore } from "@/stores/budgets";

////////////////////////////////////////////////////////////////////////
//
const router = useRouter();
const ctx = useAccountContextStore();
const budgets = useBudgetsStore();

const {
  groups: displayTransactions,
  allocationsByTx: allocsByTx,
  loading,
  loadingMore,
  loadMoreError,
  loadMore,
  error,
  assignmentsError,
  sentinel,
  activeFilter,
  query: searchQuery,
  clearSearch,
  showTransfers: showInternalTxs,
  toggleTransfers: toggleInternalTxs,
} = useTransactionList();

const searchInput = ref<HTMLInputElement | null>(null);
const { open: searchOpen, toggle: toggleSearch } = useFindShortcut({
  input: searchInput,
  onClose: clearSearch,
  initiallyOpen: !!searchQuery.value,
});

// The infinite-scroll sentinel after the list.
function setSentinel(el: unknown) {
  sentinel.value = el instanceof HTMLElement ? el : null;
}

function openTransaction(id: string) {
  router.push({ name: "transaction-detail", params: { id } });
}
</script>

<template>
  <AppShell>
    <template #action>
      <button
        type="button"
        class="flex h-10 w-10 items-center justify-center rounded-full transition-colors"
        :class="
          showInternalTxs
            ? 'bg-ocean-400 text-white hover:bg-ocean-600'
            : 'text-neutral-700 hover:bg-neutral-100'
        "
        aria-label="Toggle transfers"
        :title="showInternalTxs ? 'Hide transfers' : 'Show transfers'"
        @click="toggleInternalTxs"
      >
        <IconArrowsRightLeft class="h-5 w-5" />
      </button>
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
          ref="searchInput"
          v-model="searchQuery"
          type="text"
          placeholder="Search transactions…"
          class="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-900 outline-none transition-colors placeholder:text-neutral-400 focus:border-ocean-400 focus:ring-1 focus:ring-ocean-400"
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
            : 'border-neutral-200 bg-white text-secondary hover:border-neutral-300'
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
      <p
        v-if="assignmentsError"
        class="mb-3 rounded-card bg-coral-50 px-4 py-3 text-sm text-coral-600"
        role="alert"
      >
        {{ assignmentsError }}
      </p>

      <TransactionGroupList
        v-if="displayTransactions.length > 0"
        :groups="displayTransactions"
        :allocations-by-tx="allocsByTx"
        :budget-names="budgets.names"
        :unallocated-budget-id="ctx.unallocatedBudgetId"
        @select="openTransaction"
      />

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
      <div :ref="setSentinel" class="h-px" />

      <!-- Loading more indicator -->
      <div v-if="loadingMore" class="flex justify-center py-4">
        <div
          class="h-5 w-5 animate-spin rounded-full border-2 border-neutral-300 border-t-ocean-400"
        />
      </div>
      <p v-else-if="loadMoreError" class="py-4 text-center text-sm text-coral-600" role="alert">
        Couldn't load more transactions: {{ loadMoreError }}
        <button type="button" class="ml-1 font-medium underline" @click="loadMore">
          Try again
        </button>
      </p>
    </template>
  </AppShell>
</template>
