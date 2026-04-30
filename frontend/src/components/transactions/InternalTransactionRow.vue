<script setup lang="ts">
//
// InternalTransactionRow — list-row card for a budget-to-budget transfer.
//
// Layout:
//   [ ⇄  Transfer                           ] [ ±$amount ]
//   [ Grocery (now $45) → Dining (now $120) ]
//
// In budget-relative mode (budget detail view), the amount is signed:
// positive when this budget received the funds, negative when it sent them.
// src_budget_balance / dst_budget_balance are post-transfer snapshots.
//

// 3rd party imports
//
import { IconArrowsRightLeft } from "@tabler/icons-vue";
import { computed } from "vue";

// app imports
//
import MoneyAmount from "@/components/shared/MoneyAmount.vue";
import type { InternalTransaction } from "@/types/api";

////////////////////////////////////////////////////////////////////////
//
const props = defineProps<{
  internalTransaction: InternalTransaction;
  budgetNames?: Map<string, string>;
  relativeToBudgetId?: string;
}>();

const itx = computed(() => props.internalTransaction);

const srcName = computed(() => props.budgetNames?.get(itx.value.src_budget) ?? "Budget");
const dstName = computed(() => props.budgetNames?.get(itx.value.dst_budget) ?? "Budget");

// In budget-relative mode, sign the amount: positive if this budget
// received the transfer (dst), negative if it sent (src).
const displayAmount = computed(() => {
  const rel = props.relativeToBudgetId;
  if (!rel) return itx.value.amount;
  if (itx.value.dst_budget === rel) return itx.value.amount;
  return `-${itx.value.amount}`;
});

function fmt(amount: string): string {
  const n = Number.parseFloat(amount);
  const abs = Math.abs(n);
  const s = abs % 1 === 0 ? `$${abs.toFixed(0)}` : `$${abs.toFixed(2)}`;
  return n < 0 ? `-${s}` : s;
}
</script>

<template>
  <article class="rounded-card border border-dashed border-neutral-200 bg-white px-4 py-3">
    <!-- Row 1: icon + label + amount -->
    <div class="flex items-start justify-between gap-2">
      <div class="flex min-w-0 items-center gap-1.5">
        <IconArrowsRightLeft class="h-3.5 w-3.5 flex-none text-neutral-400" />
        <span class="text-[15px] font-medium text-neutral-600">Transfer</span>
      </div>
      <MoneyAmount
        :amount="displayAmount"
        :currency="itx.amount_currency"
        size="md"
        :coloured="!!relativeToBudgetId"
      />
    </div>

    <!-- Row 2: "Src (now $X) → Dst (now $Y)" -->
    <div class="mt-0.5 text-[12px] text-neutral-500">
      {{ srcName }}
      <span class="text-neutral-400">(now {{ fmt(itx.src_budget_balance) }})</span>
      →
      {{ dstName }}
      <span class="text-neutral-400">(now {{ fmt(itx.dst_budget_balance) }})</span>
    </div>
  </article>
</template>
