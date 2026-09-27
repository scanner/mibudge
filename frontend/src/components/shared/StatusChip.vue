<script setup lang="ts">
//
// StatusChip — small pill for budget/transaction status.  Colour pairs
// mirror the semantic mapping in UI_SPEC.md §2.2.
//

// 3rd party imports
//
import { computed } from "vue";

// app imports
//
import type { BudgetStatus } from "@/domain/budgetStatus";

////////////////////////////////////////////////////////////////////////
//

interface Props {
  status: BudgetStatus;
  label?: string;
}

const props = defineProps<Props>();

////////////////////////////////////////////////////////////////////////
//
const palette: Record<
  BudgetStatus,
  { bg: string; text: string; label: string }
> = {
  funded: { bg: "bg-success-bg", text: "text-success-fg", label: "Funded" },
  progress: { bg: "bg-info-bg", text: "text-info-fg", label: "In progress" },
  warn: { bg: "bg-warning-bg", text: "text-warning-fg", label: "Behind pace" },
  over: { bg: "bg-danger-bg", text: "text-danger-fg", label: "Overspent" },
  paused: { bg: "bg-surface-muted", text: "text-fg-muted", label: "Paused" },
};

const entry = computed(() => palette[props.status]);
const text = computed(() => props.label ?? entry.value.label);
</script>

<template>
  <span
    class="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium"
    :class="[entry.bg, entry.text]"
  >
    {{ text }}
  </span>
</template>
