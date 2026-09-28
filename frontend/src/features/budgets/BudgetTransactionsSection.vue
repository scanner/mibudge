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
import BaseIconButton from "@/components/base/BaseIconButton.vue";
import BaseInput from "@/components/base/BaseInput.vue";
import BaseSectionHeader from "@/components/base/BaseSectionHeader.vue";
import BaseSkeleton from "@/components/base/BaseSkeleton.vue";

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
      <BaseSectionHeader title="Transactions" />
      <div class="flex items-center gap-4">
        <BaseIconButton
          :label="showInternalTxs ? 'Hide transfers' : 'Show transfers'"
          size="sm"
          :pressed="showInternalTxs"
          :title="showInternalTxs ? 'Hide transfers' : 'Show transfers'"
          @click="toggleInternalTxs"
        >
          <IconArrowsRightLeft class="size-icon-sm" />
        </BaseIconButton>
        <BaseIconButton
          label="Search transactions"
          size="sm"
          @click="toggleSearch"
        >
          <IconSearch v-if="!searchOpen" class="size-icon-sm" />
          <IconX v-else class="size-icon-sm" />
        </BaseIconButton>
      </div>
    </div>

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

    <p v-if="txError" class="mb-2 text-body-sm text-danger-fg" role="alert">
      {{ txError }}
    </p>

    <div v-if="txLoading" class="space-y-2">
      <BaseSkeleton v-for="i in 3" :key="i" class="h-16" />
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

    <p v-else-if="!txError" class="py-4 text-center text-body-sm text-fg-muted">
      {{
        searchQuery
          ? "No matching transactions."
          : "No transactions assigned to this budget yet."
      }}
    </p>
  </section>
</template>
