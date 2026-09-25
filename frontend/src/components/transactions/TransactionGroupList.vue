<script setup lang="ts">
//
// TransactionGroupList — transactions and transfers under sticky date
// headers.  Presentational: rows emit `select` / `remove` with the
// transaction id.  Used by the transaction list and the budget detail
// view, which differ in heading level and in whether rows are
// removable and transfers signed relative to one budget.
//

// app imports
//
import InternalTransactionRow from "./InternalTransactionRow.vue";
import TransactionRow from "./TransactionRow.vue";
import type { DateGroup } from "@/composables/useDateGroupedRows";
import type { Allocation } from "@/models/allocation";
import type { TransactionListRow } from "@/models/listRow";
import { rowKey } from "@/models/listRow";

////////////////////////////////////////////////////////////////////////
//
withDefaults(
  defineProps<{
    groups: DateGroup<TransactionListRow>[];
    allocationsByTx: Map<string, Allocation[]> | null;
    budgetNames: Map<string, string>;
    unallocatedBudgetId: string | null;
    headingTag?: "h2" | "h3";
    removable?: boolean;
    relativeToBudgetId?: string;
  }>(),
  { headingTag: "h2", removable: false, relativeToBudgetId: undefined },
);

const emit = defineEmits<{
  (e: "select", transactionId: string): void;
  (e: "remove", transactionId: string): void;
}>();
</script>

<template>
  <div class="space-y-4">
    <section v-for="group in groups" :key="group.date">
      <component
        :is="headingTag"
        class="sticky top-0 z-10 -mx-4 bg-neutral-50/95 px-4 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-secondary backdrop-blur-sm"
      >
        {{ group.label }}
      </component>
      <div class="space-y-2">
        <template v-for="row in group.rows" :key="rowKey(row)">
          <TransactionRow
            v-if="row.kind === 'tx'"
            :transaction="row.tx"
            :allocations="allocationsByTx?.get(row.tx.id)"
            :budget-names="budgetNames"
            :unallocated-budget-id="unallocatedBudgetId"
            :removable="removable"
            @select="emit('select', $event)"
            @remove="emit('remove', $event)"
          />
          <InternalTransactionRow
            v-else
            :internal-transaction="row.itx"
            :budget-names="budgetNames"
            :relative-to-budget-id="relativeToBudgetId"
          />
        </template>
      </div>
    </section>
  </div>
</template>
