<script setup lang="ts">
//
// TransactionsView — transaction list with filter chips, date-grouped
// rows, infinite scroll, and search.  Route shell over
// `useTransactionList`; Cmd/Ctrl-F opens the search.
//

// 3rd party imports
//
import { IconArrowsRightLeft, IconSearch, IconX } from "@tabler/icons-vue";
import { ref } from "vue";
import { useRouter } from "vue-router";

// app imports
//
import EmptyState from "@/components/base/EmptyState.vue";
import TransactionGroupList from "@/components/transactions/TransactionGroupList.vue";
import { useFindShortcut } from "@/composables/useFindShortcut";
import { FILTER_CHIPS as filterChips } from "@/features/transactions/useTransactionList";
import { useTransactionList } from "@/features/transactions/useTransactionList";
import AppShell from "@/features/shell/AppShell.vue";
import { useAccountContextStore } from "@/stores/accountContext";
import { useBudgetsStore } from "@/stores/budgets";
import BaseIconButton from "@/components/base/BaseIconButton.vue";
import BaseInput from "@/components/base/BaseInput.vue";
import BaseBanner from "@/components/base/BaseBanner.vue";
import BaseSkeleton from "@/components/base/BaseSkeleton.vue";

////////////////////////////////////////////////////////////////////////
//
const router = useRouter();
const ctx = useAccountContextStore();
const budgets = useBudgetsStore();

const {
  groups: displayTransactions,
  loading,
  loadingMore,
  loadMoreError,
  loadMore,
  error,
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
      <BaseIconButton
        label="Toggle transfers"
        :pressed="showInternalTxs"
        :title="showInternalTxs ? 'Hide transfers' : 'Show transfers'"
        @click="toggleInternalTxs"
      >
        <IconArrowsRightLeft class="size-icon-md" />
      </BaseIconButton>
      <BaseIconButton label="Search transactions" @click="toggleSearch">
        <IconSearch v-if="!searchOpen" class="size-icon-md" />
        <IconX v-else class="size-icon-md" />
      </BaseIconButton>
    </template>

    <!-- Search bar -->
    <Transition
      enter-active-class="transition-all duration-base ease-enter"
      enter-from-class="max-h-0 opacity-0"
      enter-to-class="max-h-12 opacity-100"
      leave-active-class="transition-all duration-fast ease-exit"
      leave-from-class="max-h-12 opacity-100"
      leave-to-class="max-h-0 opacity-0"
    >
      <div v-if="searchOpen" class="-mx-page-x overflow-hidden px-page-x pb-3">
        <BaseInput
          ref="searchInput"
          v-model="searchQuery"
          type="text"
          placeholder="Search transactions…"
        />
      </div>
    </Transition>

    <!-- Filter chips -->
    <div
      class="-mx-page-x mb-4 flex gap-2 overflow-x-auto px-page-x pt-1 scrollbar-none"
    >
      <button
        v-for="chip in filterChips"
        :key="chip.key"
        type="button"
        class="flex-none rounded-pill border px-3 py-1 text-meta font-medium transition-colors"
        :class="
          activeFilter === chip.key
            ? 'border-accent-border bg-accent-subtle text-accent-fg'
            : 'border-border bg-surface text-fg-muted hover:border-border-emphasis'
        "
        @click="activeFilter = chip.key"
      >
        {{ chip.label }}
      </button>
    </div>

    <!-- Loading skeletons -->
    <div v-if="loading" class="space-y-3">
      <BaseSkeleton v-for="i in 6" :key="i" class="h-16" />
    </div>

    <!-- Error -->
    <BaseBanner v-else-if="error" tone="danger">
      {{ error }}
    </BaseBanner>

    <!-- Transaction list -->
    <template v-else>
      <TransactionGroupList
        v-if="displayTransactions.length > 0"
        :groups="displayTransactions"
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
          class="h-5 w-5 animate-spin rounded-pill border-2 border-border border-t-accent"
        />
      </div>
      <p
        v-else-if="loadMoreError"
        class="py-4 text-center text-body-sm text-danger-fg"
        role="alert"
      >
        Couldn't load more transactions: {{ loadMoreError }}
        <button
          type="button"
          class="ml-1 font-medium underline"
          @click="loadMore"
        >
          Try again
        </button>
      </p>
    </template>
  </AppShell>
</template>
