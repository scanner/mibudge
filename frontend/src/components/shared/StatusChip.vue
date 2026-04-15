<script setup lang="ts">
//
// StatusChip — small pill for budget/transaction status.  Colour pairs
// mirror the semantic mapping in UI_SPEC.md §2.2.
//

// 3rd party imports
//
import { computed } from "vue";

////////////////////////////////////////////////////////////////////////
//
export type BudgetStatus = "funded" | "progress" | "warn" | "over" | "paused";

interface Props {
  status: BudgetStatus;
  label?: string;
}

const props = defineProps<Props>();

////////////////////////////////////////////////////////////////////////
//
const palette: Record<BudgetStatus, { bg: string; text: string; label: string }> = {
  funded: { bg: "bg-mint-50", text: "text-mint-600", label: "Funded" },
  progress: { bg: "bg-ocean-50", text: "text-ocean-600", label: "In progress" },
  warn: { bg: "bg-amber-50", text: "text-amber-600", label: "Behind pace" },
  over: { bg: "bg-coral-50", text: "text-coral-600", label: "Overspent" },
  paused: { bg: "bg-neutral-100", text: "text-neutral-600", label: "Paused" },
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
