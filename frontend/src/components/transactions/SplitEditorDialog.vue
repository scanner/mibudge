<script setup lang="ts">
//
// SplitEditorDialog -- edit a transaction's budget allocations.
//
// Shows current splits as editable rows (budget selector + amount).
// A "+" button appends a new empty row.  A footer shows the unallocated
// remainder in ocean-blue, or the over-allocated amount in coral.
// Save is disabled when over-allocated or any row is incomplete.
// Any remainder is assigned by the backend to the unallocated budget.
//
// Presentational: emits `save` with the splits body (budget id →
// positive amount) or `cancel`.  `useModal` provides the scroll lock,
// Escape-to-cancel and focus return.
//

// 3rd party imports
//
import { IconPlus, IconX } from "@tabler/icons-vue";
import Decimal from "decimal.js";
import { computed, nextTick, ref, watch } from "vue";

// app imports
//
import { useModal } from "@/composables/useModal";
import { formatMoney, Money } from "@/domain/money";
import type { Budget } from "@/models/budget";
import { isAssignableBudget } from "@/models/budget";

////////////////////////////////////////////////////////////////////////
//
const props = withDefaults(
  defineProps<{
    open: boolean;
    budgets: Budget[];
    transactionAmount: Money;
    initialSplits: { budgetId: string; amount: string }[];
    unallocatedBudgetId?: string | null;
  }>(),
  { unallocatedBudgetId: null },
);

const emit = defineEmits<{
  (e: "save", splits: Record<string, string>): void;
  (e: "cancel"): void;
}>();

////////////////////////////////////////////////////////////////////////
//
interface SplitRow {
  budgetId: string;
  amount: string;
}

const rows = ref<SplitRow[]>([]);

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) {
      if (props.initialSplits.length > 0) {
        rows.value = props.initialSplits.map((s) => ({ ...s }));
      } else {
        // Pre-fill the first row with the full transaction amount so a
        // single-budget assignment only requires picking a budget.
        rows.value = [{ budgetId: "", amount: txTotal.value.toFixed(2) }];
      }
    } else {
      rows.value = [];
    }
  },
);

////////////////////////////////////////////////////////////////////////
//
function addRow() {
  const rem = txTotal.value.minus(splitTotal.value);

  if (rem.greaterThan(0)) {
    // Unallocated remainder exists — pre-fill the new row with it so the
    // user only needs to pick a budget to complete the split.
    rows.value.push({ budgetId: "", amount: rem.toFixed(2) });
  } else if (rows.value.length > 0) {
    // Fully allocated — split the last row's amount in half (floor) so
    // both rows together still equal the original amount.
    const last = rows.value[rows.value.length - 1];
    const lastAmt = new Decimal(last.amount || "0").abs();
    const half = lastAmt.dividedBy(2).toDecimalPlaces(2, Decimal.ROUND_DOWN);
    last.amount = lastAmt.minus(half).toFixed(2);
    rows.value.push({ budgetId: "", amount: half.toFixed(2) });
  } else {
    rows.value.push({ budgetId: "", amount: txTotal.value.toFixed(2) });
  }

  nextTick(() => {
    const selects = document.querySelectorAll<HTMLSelectElement>(".split-row-select");
    selects[selects.length - 1]?.focus();
  });
}

function removeRow(i: number) {
  rows.value.splice(i, 1);
}

////////////////////////////////////////////////////////////////////////
//
const selectableBudgets = computed(() =>
  props.budgets.filter((b) => isAssignableBudget(b, props.unallocatedBudgetId)),
);

// Budgets available for a given row = all selectable budgets minus those
// chosen by other rows (duplicates are not allowed).
function availableForRow(rowIndex: number): Budget[] {
  const taken = new Set(
    rows.value.filter((r, i) => i !== rowIndex && r.budgetId).map((r) => r.budgetId),
  );
  return selectableBudgets.value.filter((b) => !taken.has(b.id));
}

// Format the budget's current balance for the option label, in the
// budget's own currency.
//
function formatBalance(b: Budget): string {
  return formatMoney(b.balance);
}

// Label rendered in the <option>: budget name + its current balance,
// matching the "Name ($X left)" pattern used elsewhere in the
// transaction UI.
function budgetLabel(b: Budget): string {
  return `${b.name} (${formatBalance(b)} left)`;
}

// Needed for the option label when a budget is already in the list but
// belongs to this row's selection (always include it, even if absent from
// availableForRow due to another row occupying the same slot momentarily).
function fallbackBudgetLabel(id: string): string {
  const b = props.budgets.find((bb) => bb.id === id);
  return b ? budgetLabel(b) : "Budget";
}

////////////////////////////////////////////////////////////////////////
//
const txTotal = computed(() => props.transactionAmount.amount.abs());

// A row's amount as it is sent: positive and rounded to cents.  The
// remainder and the over-allocation check use the same value, so a
// split that passes the check never exceeds the transaction once sent.
// `null` when the text is not a number.
//
function rowAmount(row: SplitRow): Decimal | null {
  try {
    return new Decimal(row.amount || "0").abs().toDecimalPlaces(2);
  } catch {
    return null;
  }
}

const splitTotal = computed(() =>
  rows.value.reduce((sum, r) => sum.plus(rowAmount(r) ?? 0), new Decimal(0)),
);

const remainder = computed(() => txTotal.value.minus(splitTotal.value));
const isOver = computed(() => remainder.value.lessThan(0));

////////////////////////////////////////////////////////////////////////
//
const canSave = computed(() => {
  if (isOver.value) return false;
  if (rows.value.length === 0) return true;
  return rows.value.every((r) => !!r.budgetId && !!rowAmount(r)?.greaterThan(0));
});

function save() {
  if (!canSave.value) return;
  const splits: Record<string, string> = {};
  for (const row of rows.value) {
    if (row.budgetId) {
      splits[row.budgetId] = rowAmount(row)!.toFixed(2);
    }
  }
  emit("save", splits);
}

useModal(
  () => props.open,
  () => emit("cancel"),
);
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="open" class="fixed inset-0 z-50 flex items-end justify-center md:items-center">
        <div class="absolute inset-0 bg-neutral-900/40" @click="emit('cancel')" />

        <div
          class="relative flex max-h-[80vh] w-full flex-col rounded-t-2xl bg-white shadow-xl md:w-[480px] md:rounded-card"
          role="dialog"
          aria-modal="true"
          aria-label="Edit allocations"
        >
          <!-- Header -->
          <div class="flex items-center justify-between border-b border-neutral-200 px-5 pb-3 pt-5">
            <h2 class="text-base font-medium text-neutral-900">Allocations</h2>
            <button
              type="button"
              class="text-sm text-neutral-500 hover:text-neutral-700"
              @click="emit('cancel')"
            >
              Cancel
            </button>
          </div>

          <!-- Split rows -->
          <div class="flex-1 overflow-y-auto px-4 py-3">
            <div class="space-y-2">
              <div v-for="(row, i) in rows" :key="i" class="flex items-center gap-2">
                <!-- Budget selector -->
                <select
                  v-model="row.budgetId"
                  class="split-row-select min-w-0 flex-1 rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-1.5 text-sm text-neutral-900 outline-none focus:border-ocean-400"
                >
                  <option value="">Select budget…</option>
                  <option v-for="b in availableForRow(i)" :key="b.id" :value="b.id">
                    {{ budgetLabel(b) }}
                  </option>
                  <!-- Keep the current selection visible even when temporarily
                       displaced by another row's selection. -->
                  <option
                    v-if="row.budgetId && !availableForRow(i).find((b) => b.id === row.budgetId)"
                    :value="row.budgetId"
                  >
                    {{ fallbackBudgetLabel(row.budgetId) }}
                  </option>
                </select>

                <!-- Amount input -->
                <input
                  v-model="row.amount"
                  type="text"
                  inputmode="decimal"
                  placeholder="0.00"
                  class="w-24 flex-none rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-1.5 text-right font-mono text-sm text-neutral-900 outline-none focus:border-ocean-400"
                />

                <!-- Remove row -->
                <button
                  type="button"
                  class="flex h-6 w-6 flex-none items-center justify-center rounded-full text-neutral-400 hover:bg-coral-50 hover:text-coral-600"
                  aria-label="Remove split"
                  @click="removeRow(i)"
                >
                  <IconX class="h-3.5 w-3.5" />
                </button>
              </div>
            </div>

            <!-- Add row button -->
            <button
              type="button"
              class="mt-2 flex items-center gap-1.5 px-1 py-1.5 text-sm font-medium text-ocean-600 hover:text-ocean-800"
              @click="addRow"
            >
              <IconPlus class="h-4 w-4" />
              Add split
            </button>
          </div>

          <!-- Footer: remainder indicator + Save -->
          <div class="border-t border-neutral-200 px-4 py-3">
            <div class="mb-3 flex items-center justify-between text-sm">
              <span :class="isOver ? 'font-medium text-coral-600' : 'text-neutral-500'">
                {{ isOver ? "Over by" : "Unallocated" }}
              </span>
              <span
                :class="['font-mono font-medium', isOver ? 'text-coral-600' : 'text-ocean-600']"
              >
                {{ formatMoney(Money.of(remainder.abs(), transactionAmount.currency)) }}
              </span>
            </div>

            <button
              type="button"
              class="w-full rounded-lg px-4 py-2 text-sm font-medium transition-colors"
              :class="
                canSave
                  ? 'bg-ocean-600 text-white hover:bg-ocean-800'
                  : 'cursor-not-allowed bg-neutral-200 text-neutral-400'
              "
              :disabled="!canSave"
              @click="save"
            >
              Save
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 120ms ease-out;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
