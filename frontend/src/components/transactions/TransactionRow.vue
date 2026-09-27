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
// left border is shown.  Pending transactions show "Unallocated (X left)";
// posted transactions show the "Unallocated — tap to assign" prompt.
//
// Presentational: clicking the row emits `select`, the remove button
// (when `removable`) emits `remove`; the parent acts on them.
//

// 3rd party imports
//
import { IconX } from "@tabler/icons-vue";
import { computed } from "vue";

// app imports
//
import MoneyAmount from "@/components/shared/MoneyAmount.vue";
import { transactionTypeLabel } from "@/domain/labels";
import { formatMoney } from "@/domain/money";
import type { Money } from "@/domain/money";
import type { Allocation } from "@/models/allocation";
import { isUnallocated } from "@/models/allocation";
import type { Transaction } from "@/models/transaction";
import { displayName } from "@/models/transaction";

////////////////////////////////////////////////////////////////////////
//
const props = withDefaults(
  defineProps<{
    transaction: Transaction;
    allocations?: Allocation[];
    budgetNames?: Map<string, string>;
    unallocatedBudgetId?: string | null;
    removable?: boolean;
  }>(),
  {
    allocations: undefined,
    budgetNames: undefined,
    unallocatedBudgetId: null,
    removable: false,
  },
);

const emit = defineEmits<{
  (e: "select", transactionId: string): void;
  (e: "remove", transactionId: string): void;
}>();

////////////////////////////////////////////////////////////////////////
//
const partyName = computed(() => displayName(props.transaction));

const typeLabel = computed(() =>
  transactionTypeLabel(props.transaction.transactionType),
);

////////////////////////////////////////////////////////////////////////
//
// Allocation display logic.  Determines what to show below the party name.
//
interface AllocDisplay {
  name: string;
  amount: Money;
  balance: Money;
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
  const empty = {
    isUnallocated: false,
    isSplit: false,
    single: null,
    allLegs: [],
  };
  if (!allocs || allocs.length === 0) return empty;

  if (isUnallocated(allocs, props.unallocatedBudgetId)) {
    return { isUnallocated: true, isSplit: false, single: null, allLegs: [] };
  }

  const names = props.budgetNames;
  const toDisplay = (a: Allocation): AllocDisplay => ({
    name: (a.budgetId && names?.get(a.budgetId)) || "Unallocated",
    amount: a.amount,
    balance: a.budgetBalance,
  });

  if (allocs.length === 1) {
    return {
      isUnallocated: false,
      isSplit: false,
      single: toDisplay(allocs[0]),
      allLegs: [],
    };
  }

  return {
    isUnallocated: false,
    isSplit: true,
    single: null,
    allLegs: allocs.map(toDisplay),
  };
});
</script>

<template>
  <article
    class="group/row cursor-pointer rounded-card border border-border bg-surface transition-colors hover:bg-surface-sunken"
    :class="
      transaction.pending
        ? 'border-l-rule border-l-row-pending'
        : allocInfo.isUnallocated
          ? 'border-l-rule border-l-row-unallocated'
          : ''
    "
    @click="emit('select', transaction.id)"
  >
    <div class="px-card-x py-card-y">
      <!-- Row 1: party name + amount (+ account balance below) + optional remove -->
      <div class="flex items-start justify-between gap-2">
        <span class="min-w-0 truncate text-item-title text-fg">
          {{ partyName }}
        </span>
        <div class="flex flex-none flex-col items-end">
          <div class="flex items-center gap-1.5">
            <MoneyAmount :amount="transaction.amount" size="md" coloured />
            <button
              v-if="removable"
              type="button"
              class="flex h-5 w-5 items-center justify-center rounded-pill text-fg-muted opacity-0 transition-opacity hover:bg-danger-bg hover:text-danger-fg group-hover/row:opacity-100"
              aria-label="Remove from budget"
              @click.stop="emit('remove', transaction.id)"
            >
              <IconX class="size-icon-xs" />
            </button>
          </div>
          <span class="tabular-nums text-meta text-fg-muted">
            {{ formatMoney(transaction.accountAvailableBalance) }}
          </span>
        </div>
      </div>

      <!-- Row 2 (unallocated): balance info for pending, tap-to-assign prompt otherwise -->
      <div
        v-if="allocInfo.isUnallocated"
        class="mt-0.5 flex items-center justify-between gap-2"
      >
        <span
          v-if="transaction.pending"
          class="min-w-0 truncate text-meta text-fg-link"
        >
          Unallocated
          <span v-if="allocations?.[0]" class="text-fg-muted">
            (now {{ formatMoney(allocations[0].budgetBalance) }})
          </span>
        </span>
        <span v-else class="min-w-0 truncate text-meta italic text-fg-muted">
          Unallocated — tap to assign
        </span>
        <div class="flex flex-none items-center gap-1.5">
          <span
            v-if="transaction.pending"
            class="rounded-xs px-1 py-0.5 text-badge uppercase text-warning-fg ring-1 ring-warning-border"
          >
            Pending
          </span>
          <span v-if="typeLabel" class="text-meta text-fg-muted">{{
            typeLabel
          }}</span>
        </div>
      </div>

      <!-- Row 2 (single budget): name + running balance -->
      <div
        v-else-if="allocInfo.single"
        class="mt-0.5 flex items-center justify-between gap-2"
      >
        <span class="min-w-0 truncate text-meta text-fg-link">
          {{ allocInfo.single.name }}
          <span class="text-fg-muted"
            >(now {{ formatMoney(allocInfo.single.balance) }})</span
          >
        </span>
        <div class="flex flex-none items-center gap-1.5">
          <span
            v-if="transaction.pending"
            class="rounded-xs px-1 py-0.5 text-badge uppercase text-warning-fg ring-1 ring-warning-border"
          >
            Pending
          </span>
          <span v-if="typeLabel" class="text-meta text-fg-muted">{{
            typeLabel
          }}</span>
        </div>
      </div>

      <!-- Rows 2+ (split): header row + one line per leg -->
      <div v-else-if="allocInfo.isSplit" class="mt-0.5">
        <div class="flex items-center justify-between gap-2">
          <span
            class="rounded-xs px-1 py-0.5 text-badge uppercase text-fg-muted ring-1 ring-border-emphasis"
          >
            Split
          </span>
          <div class="flex flex-none items-center gap-1.5">
            <span
              v-if="transaction.pending"
              class="rounded-xs px-1 py-0.5 text-badge uppercase text-warning-fg ring-1 ring-warning-border"
            >
              Pending
            </span>
            <span v-if="typeLabel" class="text-meta text-fg-muted">{{
              typeLabel
            }}</span>
          </div>
        </div>
        <div
          v-for="(leg, i) in allocInfo.allLegs"
          :key="i"
          class="mt-0.5 flex items-baseline gap-1.5"
        >
          <span class="min-w-0 flex-1 truncate text-meta text-fg-link">
            {{ leg.name }}
            <span class="text-fg-muted"
              >(now {{ formatMoney(leg.balance) }})</span
            >
          </span>
          <span class="flex-none text-meta font-medium text-fg">
            {{ formatMoney(leg.amount) }}
          </span>
        </div>
      </div>

      <!-- Row 2 (no alloc info): type label + optional pending badge -->
      <div
        v-else-if="typeLabel || transaction.pending"
        class="mt-0.5 flex justify-end gap-1.5"
      >
        <span
          v-if="transaction.pending"
          class="rounded-xs px-1 py-0.5 text-badge uppercase text-warning-fg ring-1 ring-warning-border"
        >
          Pending
        </span>
        <span v-if="typeLabel" class="text-meta text-fg-muted">{{
          typeLabel
        }}</span>
      </div>
    </div>
  </article>
</template>
