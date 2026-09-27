<script setup lang="ts">
//
// AllocationsSection — a transaction's budget allocations, how much of
// the amount they cover, and the assign / add-split button.
// Presentational: emits `update`, `remove`, `assign` and
// `navigate-budget`; the parent applies them.
//

// 3rd party imports
//
import { IconPlus } from "@tabler/icons-vue";
import { computed } from "vue";

// app imports
//
import AllocationCard from "./AllocationCard.vue";
import MoneyAmount from "@/components/shared/MoneyAmount.vue";
import type { Allocation, AllocationCoverage } from "@/models/allocation";

////////////////////////////////////////////////////////////////////////
//
const props = defineProps<{
  // Allocations to real budgets (not Unallocated).
  allocations: Allocation[];
  coverage: AllocationCoverage | null;
  pending: boolean;
  budgetName: (budgetId: string | null) => string;
}>();

const emit = defineEmits<{
  (e: "update", allocationId: string, amount: string): void;
  (e: "remove", allocationId: string): void;
  (e: "assign"): void;
  (e: "navigate-budget", budgetId: string): void;
}>();

////////////////////////////////////////////////////////////////////////
//
const STATUS = {
  full: {
    label: "Fully allocated",
    bg: "bg-success-bg",
    text: "text-success-fg",
  },
  remaining: { label: "Unassigned", bg: "bg-info-bg", text: "text-info-fg" },
  over: { label: "Over by", bg: "bg-danger-bg", text: "text-danger-fg" },
} as const;

const allocationStatus = computed(() =>
  props.coverage
    ? { ...STATUS[props.coverage.kind], amount: props.coverage.amount }
    : null,
);
</script>

<template>
  <section class="mt-6">
    <h2 class="mb-2 text-overline uppercase text-fg-muted">Allocations</h2>

    <div v-if="allocations.length > 0" class="space-y-2">
      <AllocationCard
        v-for="alloc in allocations"
        :key="alloc.id"
        :allocation="alloc"
        :budget-name="budgetName(alloc.budgetId)"
        @update="(id, amount) => emit('update', id, amount)"
        @remove="emit('remove', $event)"
        @reassign="emit('assign')"
        @navigate-budget="emit('navigate-budget', $event)"
      />
    </div>

    <!-- Allocation status indicator (only when real allocations exist) -->
    <div
      v-if="allocations.length > 0 && allocationStatus"
      class="mt-3 flex items-center justify-between rounded-control px-3 py-2 text-label"
      :class="[allocationStatus.bg, allocationStatus.text]"
    >
      <span>{{ allocationStatus.label }}</span>
      <MoneyAmount :amount="allocationStatus.amount" size="sm" />
    </div>

    <!-- Assign / add split button.  Pending transactions cannot be
         allocated to user budgets -- the server rejects the action
         and the UI carries only the auto Unallocated row until the
         transaction posts.  When pending, swap the call-to-action
         for a quiet explanatory note so the section reads clearly
         rather than silently dropping the row. -->
    <button
      v-if="!pending"
      type="button"
      class="mt-3 flex w-full items-center justify-center gap-1.5 rounded-control border border-dashed border-info-border px-3 py-2 text-label text-info-fg transition-colors hover:border-accent-border hover:bg-accent-subtle"
      @click="emit('assign')"
    >
      <IconPlus class="size-icon-sm" />
      {{ allocations.length > 0 ? "Add split" : "Assign to budget" }}
    </button>
    <p v-else class="mt-3 px-3 py-2 text-center text-body-sm text-fg-muted">
      Pending transactions can't be assigned to a budget. The allocation becomes
      editable once the bank posts this transaction.
    </p>
  </section>
</template>
