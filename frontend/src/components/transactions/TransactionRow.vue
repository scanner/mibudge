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
import { IconX } from "@tabler/icons-vue";
import { computed } from "vue";
import { useRouter } from "vue-router";

// app imports
//
import MoneyAmount from "@/components/shared/MoneyAmount.vue";
import { TRANSACTION_TYPE_LABELS } from "@/types/api";
import type { Transaction, TransactionAllocation } from "@/types/api";

////////////////////////////////////////////////////////////////////////
//
const props = withDefaults(
  defineProps<{
    transaction: Transaction;
    allocations?: TransactionAllocation[];
    budgetNames?: Map<string, string>;
    unallocatedBudgetId?: string | null;
    removable?: boolean;
  }>(),
  { removable: false },
);

const emit = defineEmits<{
  (e: "remove", transactionId: string): void;
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
interface AllocDisplay {
  name: string;
  balance: string;
  currency: string;
}

const allocInfo = computed<{
  text: string;
  isUnallocated: boolean;
  isSplit: boolean;
  budgets: AllocDisplay[];
}>(() => {
  const allocs = props.allocations;
  if (!allocs || allocs.length === 0) {
    return { text: "", isUnallocated: false, isSplit: false, budgets: [] };
  }

  const unallocId = props.unallocatedBudgetId;
  const names = props.budgetNames;

  const allUnallocated = allocs.every((a) => a.budget === unallocId || a.budget === null);
  if (allUnallocated) {
    return {
      text: "Unallocated — tap to assign",
      isUnallocated: true,
      isSplit: false,
      budgets: [],
    };
  }

  const budgets: AllocDisplay[] = allocs
    .filter((a) => a.budget && a.budget !== unallocId)
    .map((a) => ({
      name: names?.get(a.budget!) ?? "Budget",
      balance: a.budget_balance,
      currency: a.budget_balance_currency,
    }));

  if (allocs.length === 1) {
    return { text: "", isUnallocated: false, isSplit: false, budgets };
  }

  return { text: "", isUnallocated: false, isSplit: true, budgets };
});

function fmtBalance(b: AllocDisplay): string {
  const n = Number.parseFloat(b.balance);
  const abs = Math.abs(n);
  const formatted = abs % 1 === 0 ? `$${abs.toFixed(0)}` : `$${abs.toFixed(2)}`;
  return n < 0 ? `-${formatted}` : formatted;
}
</script>

<template>
  <article
    class="group/row cursor-pointer rounded-card border border-neutral-200 bg-white transition-colors hover:bg-neutral-50"
    :class="allocInfo.isUnallocated ? 'border-l-[3px] border-l-ocean-400' : ''"
    @click="router.push(`/transactions/${transaction.id}/`)"
  >
    <div class="px-4 py-3">
      <!-- Row 1: party name + amount + optional remove -->
      <div class="flex items-start justify-between gap-2">
        <span class="min-w-0 truncate text-[15px] font-medium text-neutral-900">
          {{ partyName }}
        </span>
        <div class="flex flex-none items-center gap-1.5">
          <MoneyAmount
            :amount="transaction.amount"
            :currency="transaction.amount_currency"
            size="md"
            coloured
          />
          <button
            v-if="removable"
            type="button"
            class="flex h-5 w-5 items-center justify-center rounded-full text-neutral-400 opacity-0 transition-opacity hover:bg-coral-50 hover:text-coral-600 group-hover/row:opacity-100"
            aria-label="Remove from budget"
            @click.stop="emit('remove', transaction.id)"
          >
            <IconX class="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <!-- Row 2: allocation info + type label -->
      <div class="mt-0.5 flex items-center justify-between gap-2">
        <span
          v-if="allocInfo.isUnallocated"
          class="min-w-0 truncate text-[12px] italic text-neutral-500"
        >
          Unallocated — tap to assign
        </span>
        <span
          v-else-if="allocInfo.budgets.length > 0"
          class="min-w-0 truncate text-[12px] text-ocean-600"
        >
          <template v-for="(b, i) in allocInfo.budgets" :key="i">
            <template v-if="i > 0">, </template>
            {{ b.name }}
            <span class="text-neutral-400">({{ fmtBalance(b) }} left)</span>
          </template>
        </span>
        <span v-else class="flex-1" />
        <span v-if="typeLabel" class="flex-none text-[12px] text-neutral-400">
          {{ typeLabel }}
        </span>
      </div>
    </div>
  </article>
</template>
