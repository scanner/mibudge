<script setup lang="ts">
//
// TransactionRow — list-row card for a single transaction.  (UI_SPEC §4.5)
//
// Layout (non-split):
//   [ Party name               ] [ $amount ]
//   [ allocation · type label  ] [         ]
//
// Layout (split):
//   [ Party name               ] [ $amount ]
//   [ SPLIT pill  ] [ type label           ]
//   [ Budget A    ] [ -$30 ] [ ($370 left) ]
//   [ Budget B    ] [ -$70 ] [ ($200 left) ]
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
// Allocation display logic.  Determines what to show below the party name.
//
interface AllocDisplay {
  name: string;
  amount: string;
  balance: string;
}

const allocInfo = computed<{
  isUnallocated: boolean;
  isSplit: boolean;
  // Single non-split allocation (isSplit=false, not unallocated).
  single: AllocDisplay | null;
  // All legs for split display, including any Unallocated portion.
  allLegs: AllocDisplay[];
}>(() => {
  const allocs = props.allocations;
  const empty = { isUnallocated: false, isSplit: false, single: null, allLegs: [] };
  if (!allocs || allocs.length === 0) return empty;

  const unallocId = props.unallocatedBudgetId;
  const names = props.budgetNames;

  const allUnallocated = allocs.every((a) => a.budget === unallocId || a.budget === null);
  if (allUnallocated) {
    return { isUnallocated: true, isSplit: false, single: null, allLegs: [] };
  }

  const toDisplay = (a: TransactionAllocation): AllocDisplay => ({
    name: (a.budget && names?.get(a.budget)) ?? "Unallocated",
    amount: a.amount,
    balance: a.budget_balance,
  });

  if (allocs.length === 1) {
    return { isUnallocated: false, isSplit: false, single: toDisplay(allocs[0]), allLegs: [] };
  }

  return {
    isUnallocated: false,
    isSplit: true,
    single: null,
    allLegs: allocs.map(toDisplay),
  };
});

function fmtMoney(raw: string): string {
  const n = Number.parseFloat(raw);
  const abs = Math.abs(n);
  const formatted = abs % 1 === 0 ? `$${abs.toFixed(0)}` : `$${abs.toFixed(2)}`;
  return n < 0 ? `-${formatted}` : formatted;
}

function fmtAccountBalance(raw: string, currency: string): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
  }).format(Number.parseFloat(raw));
}
</script>

<template>
  <article
    class="group/row cursor-pointer rounded-card border border-neutral-200 bg-white transition-colors hover:bg-neutral-50"
    :class="
      transaction.pending
        ? 'border-l-[3px] border-l-amber-400'
        : allocInfo.isUnallocated
          ? 'border-l-[3px] border-l-ocean-400'
          : ''
    "
    @click="router.push(`/transactions/${transaction.id}/`)"
  >
    <div class="px-4 py-3">
      <!-- Row 1: party name + amount (+ account balance below) + optional remove -->
      <div class="flex items-start justify-between gap-2">
        <span class="min-w-0 truncate text-[15px] font-medium text-neutral-900">
          {{ partyName }}
        </span>
        <div class="flex flex-none flex-col items-end">
          <div class="flex items-center gap-1.5">
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
          <span
            v-if="transaction.bank_account_available_balance"
            class="tabular-nums text-[11px] text-secondary"
          >
            {{
              fmtAccountBalance(
                transaction.bank_account_available_balance,
                transaction.bank_account_available_balance_currency,
              )
            }}
          </span>
        </div>
      </div>

      <!-- Row 2 (unallocated): italic prompt -->
      <div v-if="allocInfo.isUnallocated" class="mt-0.5 flex items-center justify-between gap-2">
        <span class="min-w-0 truncate text-[12px] italic text-secondary">
          Unallocated — tap to assign
        </span>
        <div class="flex flex-none items-center gap-1.5">
          <span
            v-if="transaction.pending"
            class="rounded px-1 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-600 ring-1 ring-amber-300"
          >
            Pending
          </span>
          <span v-if="typeLabel" class="text-[12px] text-secondary">{{ typeLabel }}</span>
        </div>
      </div>

      <!-- Row 2 (single budget): name + running balance -->
      <div v-else-if="allocInfo.single" class="mt-0.5 flex items-center justify-between gap-2">
        <span class="min-w-0 truncate text-[12px] text-ocean-600">
          {{ allocInfo.single.name }}
          <span class="text-secondary">({{ fmtMoney(allocInfo.single.balance) }} left)</span>
        </span>
        <div class="flex flex-none items-center gap-1.5">
          <span
            v-if="transaction.pending"
            class="rounded px-1 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-600 ring-1 ring-amber-300"
          >
            Pending
          </span>
          <span v-if="typeLabel" class="text-[12px] text-secondary">{{ typeLabel }}</span>
        </div>
      </div>

      <!-- Rows 2+ (split): header row + one line per leg -->
      <div v-else-if="allocInfo.isSplit" class="mt-0.5">
        <div class="flex items-center justify-between gap-2">
          <span
            class="rounded px-1 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-secondary ring-1 ring-neutral-300"
          >
            Split
          </span>
          <div class="flex flex-none items-center gap-1.5">
            <span
              v-if="transaction.pending"
              class="rounded px-1 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-600 ring-1 ring-amber-300"
            >
              Pending
            </span>
            <span v-if="typeLabel" class="text-[12px] text-secondary">{{ typeLabel }}</span>
          </div>
        </div>
        <div
          v-for="(leg, i) in allocInfo.allLegs"
          :key="i"
          class="mt-0.5 flex items-baseline gap-1.5"
        >
          <span class="min-w-0 flex-1 truncate text-[12px] text-ocean-600">
            {{ leg.name }}
          </span>
          <span class="flex-none text-[12px] font-medium text-neutral-700">
            {{ fmtMoney(leg.amount) }}
          </span>
          <span class="flex-none text-[11px] text-secondary">
            ({{ fmtMoney(leg.balance) }} left)
          </span>
        </div>
      </div>

      <!-- Row 2 (no alloc info): type label + optional pending badge -->
      <div v-else-if="typeLabel || transaction.pending" class="mt-0.5 flex justify-end gap-1.5">
        <span
          v-if="transaction.pending"
          class="rounded px-1 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-600 ring-1 ring-amber-300"
        >
          Pending
        </span>
        <span v-if="typeLabel" class="text-[12px] text-secondary">{{ typeLabel }}</span>
      </div>
    </div>
  </article>
</template>
