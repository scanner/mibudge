<script setup lang="ts">
//
// BudgetTransactionsSection — the transactions (and optionally the
// transfers) of one budget, grouped by date, with search and per-row
// "remove from this budget".  Feature component (budgets); data lives
// in `useBudgetTransactions`.  Cmd/Ctrl-F opens the search.
//

// 3rd party imports
//
import { IconArrowsRightLeft, IconSearch, IconX } from "@tabler/icons-vue";
import { ref } from "vue";
import { useRouter } from "vue-router";

// app imports
//
import TransactionGroupList from "@/components/transactions/TransactionGroupList.vue";
import { useFindShortcut } from "@/composables/useFindShortcut";
import { useAccountContextStore } from "@/stores/accountContext";
import { useBudgetsStore } from "@/stores/budgets";
import { useBudgetTransactions } from "./useBudgetTransactions";

////////////////////////////////////////////////////////////////////////
//
const props = defineProps<{ budgetId: string }>();

const router = useRouter();
const ctx = useAccountContextStore();
const budgets = useBudgetsStore();

const {
  allocationsByTx: budgetAllocsByTx,
  loading: txLoading,
  error: txError,
  showTransfers: showInternalTxs,
  toggleTransfers: toggleInternalTxs,
  query: searchQuery,
  clearSearch,
  groups: displayTransactions,
  removeTransaction: onRemoveTransaction,
} = useBudgetTransactions(() => props.budgetId);

const searchInput = ref<HTMLInputElement | null>(null);
const { open: searchOpen, toggle: toggleSearch } = useFindShortcut({
  input: searchInput,
  onClose: clearSearch,
});

function openTransaction(id: string) {
  router.push({ name: "transaction-detail", params: { id } });
}
</script>

<template>
  <section class="mt-2">
    <div class="mb-2 flex items-center justify-between">
      <h2 class="text-[11px] font-semibold uppercase tracking-wider text-secondary">
        Transactions
      </h2>
      <div class="flex items-center gap-1">
        <button
          type="button"
          class="flex h-7 w-7 items-center justify-center rounded-full transition-colors"
          :class="
            showInternalTxs
              ? 'bg-ocean-400 text-white hover:bg-ocean-600'
              : 'text-neutral-500 hover:bg-neutral-100'
          "
          :aria-label="showInternalTxs ? 'Hide transfers' : 'Show transfers'"
          :title="showInternalTxs ? 'Hide transfers' : 'Show transfers'"
          @click="toggleInternalTxs"
        >
          <IconArrowsRightLeft class="h-4 w-4" />
        </button>
        <button
          type="button"
          class="flex h-7 w-7 items-center justify-center rounded-full text-neutral-500 hover:bg-neutral-100"
          aria-label="Search transactions"
          @click="toggleSearch"
        >
          <IconSearch v-if="!searchOpen" class="h-4 w-4" />
          <IconX v-else class="h-4 w-4" />
        </button>
      </div>
    </div>

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

    <p v-if="txError" class="mb-2 text-sm text-coral-600" role="alert">{{ txError }}</p>

    <div v-if="txLoading" class="space-y-2">
      <div v-for="i in 3" :key="i" class="h-16 animate-pulse rounded-card bg-neutral-100" />
    </div>

    <TransactionGroupList
      v-else-if="displayTransactions.length > 0"
      :groups="displayTransactions"
      :allocations-by-tx="budgetAllocsByTx"
      :budget-names="budgets.names"
      :unallocated-budget-id="ctx.unallocatedBudgetId"
      heading-tag="h3"
      removable
      :relative-to-budget-id="budgetId"
      @select="openTransaction"
      @remove="onRemoveTransaction"
    />

    <p v-else-if="!txError" class="py-4 text-center text-sm text-secondary">
      {{
        searchQuery ? "No matching transactions." : "No transactions assigned to this budget yet."
      }}
    </p>
  </section>
</template>
