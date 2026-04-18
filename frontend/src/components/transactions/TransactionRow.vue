<script setup lang="ts">
//
// TransactionRow — list-row card for a single transaction.  (UI_SPEC §4.5)
//
// Layout:
//   [ Party name               ] [ $amount ]
//   [ allocation · type label  ] [         ]
//
// When the transaction is allocated to the unallocated budget, a blue
// left border is shown and the allocation text reads "Unallocated —
// tap to assign".
//

// 3rd party imports
//
import { computed } from "vue";
import { useRouter } from "vue-router";

// app imports
//
import MoneyAmount from "@/components/shared/MoneyAmount.vue";
import { TRANSACTION_TYPE_LABELS } from "@/types/api";
import type { Transaction, TransactionAllocation } from "@/types/api";

////////////////////////////////////////////////////////////////////////
//
const props = defineProps<{
  transaction: Transaction;
  allocations?: TransactionAllocation[];
  budgetNames?: Map<string, string>;
  unallocatedBudgetId?: string | null;
}>();

const router = useRouter();

////////////////////////////////////////////////////////////////////////
//
const partyName = computed(() => {
  const tx = props.transaction;
  return tx.party || tx.description || tx.raw_description;
});

const typeLabel = computed(() => {
  const t = props.transaction.transaction_type;
  if (!t) return "";
  return TRANSACTION_TYPE_LABELS[t] ?? t;
});

////////////////////////////////////////////////////////////////////////
//
// Allocation display logic.  Determines what to show in the second
// row of the transaction card.
//
const allocInfo = computed<{ text: string; isUnallocated: boolean; isSplit: boolean }>(() => {
  const allocs = props.allocations;
  if (!allocs || allocs.length === 0) {
    return { text: "", isUnallocated: false, isSplit: false };
  }

  // Credits go to unallocated by design — don't prompt for assignment.
  if (Number.parseFloat(props.transaction.amount) > 0) {
    return { text: "", isUnallocated: false, isSplit: false };
  }

  const unallocId = props.unallocatedBudgetId;
  const names = props.budgetNames;

  if (allocs.length === 1) {
    const a = allocs[0];
    if (a.budget === unallocId || a.budget === null) {
      return { text: "Unallocated — tap to assign", isUnallocated: true, isSplit: false };
    }
    const name = names?.get(a.budget) ?? "Budget";
    return { text: `From ${name}`, isUnallocated: false, isSplit: false };
  }

  const allUnallocated = allocs.every((a) => a.budget === unallocId || a.budget === null);
  if (allUnallocated) {
    return { text: "Unallocated — tap to assign", isUnallocated: true, isSplit: false };
  }

  const budgetLabels = allocs
    .filter((a) => a.budget && a.budget !== unallocId)
    .map((a) => names?.get(a.budget!) ?? "Budget");
  const unique = [...new Set(budgetLabels)];
  return { text: `Split: ${unique.join(", ")}`, isUnallocated: false, isSplit: true };
});
</script>

<template>
  <article
    class="cursor-pointer rounded-card border border-neutral-200 bg-white transition-colors hover:bg-neutral-50"
    :class="allocInfo.isUnallocated ? 'border-l-[3px] border-l-ocean-400' : ''"
    @click="router.push(`/transactions/${transaction.id}/`)"
  >
    <div class="px-4 py-3">
      <!-- Row 1: party name + amount -->
      <div class="flex items-start justify-between gap-2">
        <span class="min-w-0 truncate text-[15px] font-medium text-neutral-900">
          {{ partyName }}
        </span>
        <MoneyAmount
          :amount="transaction.amount"
          :currency="transaction.amount_currency"
          size="md"
          coloured
          class="flex-none"
        />
      </div>

      <!-- Row 2: allocation info + type label -->
      <div class="mt-0.5 flex items-center justify-between gap-2">
        <span
          v-if="allocInfo.text"
          class="min-w-0 truncate text-[12px]"
          :class="
            allocInfo.isUnallocated
              ? 'italic text-neutral-500'
              : allocInfo.isSplit
                ? 'text-ocean-600'
                : 'text-neutral-500'
          "
        >
          <template v-if="!allocInfo.isUnallocated && !allocInfo.isSplit">
            <span class="text-ocean-600">{{ allocInfo.text.replace("From ", "") }}</span>
          </template>
          <template v-else>{{ allocInfo.text }}</template>
        </span>
        <span v-else class="flex-1" />
        <span v-if="typeLabel" class="flex-none text-[12px] text-neutral-400">
          {{ typeLabel }}
        </span>
      </div>
    </div>
  </article>
</template>
