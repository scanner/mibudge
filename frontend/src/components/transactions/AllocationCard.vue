<script setup lang="ts">
//
// AllocationCard — renders a single allocation within a transaction
// detail view.  Shows budget name, editable amount, and category.
// Swipe-to-delete on mobile, hover × on desktop.  (UI_SPEC §4.6)
//

// 3rd party imports
//
import { IconTrash } from "@tabler/icons-vue";
import { computed, ref, watch } from "vue";

// app imports
//
import MoneyAmount from "@/components/shared/MoneyAmount.vue";
import { toDecimal } from "@/domain/money";
import type { Allocation } from "@/models/allocation";

////////////////////////////////////////////////////////////////////////
//
const props = defineProps<{
  allocation: Allocation;
  budgetName: string;
}>();

const emit = defineEmits<{
  (e: "update", id: string, amount: string): void;
  (e: "remove", id: string): void;
  (e: "reassign", id: string): void;
  (e: "navigate-budget", budgetId: string): void;
}>();

////////////////////////////////////////////////////////////////////////
//
const editingAmount = ref(false);
const amountInput = ref(props.allocation.amount.toDecimalString());

watch(
  () => props.allocation.amount,
  (v) => {
    amountInput.value = v.toDecimalString();
  },
);

function startEdit() {
  editingAmount.value = true;
}

function commitEdit() {
  editingAmount.value = false;
  const cleaned = amountInput.value.replace(/[^0-9.\-]/g, "");
  const parsed = toDecimal(cleaned);
  if (parsed && !props.allocation.amount.equals(parsed)) {
    emit("update", props.allocation.id, parsed.toFixed(2));
  } else {
    amountInput.value = props.allocation.amount.toDecimalString();
  }
}

////////////////////////////////////////////////////////////////////////
//
const budgetId = computed(() => props.allocation.budgetId);
</script>

<template>
  <div
    class="group relative rounded-card border border-border bg-surface px-4 py-3"
  >
    <!-- Remove button -->
    <button
      type="button"
      class="absolute right-2 top-2 flex h-6 w-6 items-center justify-center rounded-pill text-fg-muted opacity-0 transition-opacity hover:bg-danger-bg hover:text-danger-fg group-hover:opacity-100"
      aria-label="Remove allocation"
      @click="emit('remove', allocation.id)"
    >
      <IconTrash class="size-icon-xs" />
    </button>

    <!-- Budget name + reassign -->
    <div class="flex items-center gap-2">
      <button
        v-if="budgetId"
        type="button"
        class="text-label text-fg-link hover:underline"
        @click="emit('navigate-budget', budgetId)"
      >
        {{ budgetName }}
      </button>
      <span v-else class="text-body-sm italic text-fg-muted">Unallocated</span>
      <button
        type="button"
        class="text-meta text-fg-muted hover:text-accent-fg"
        @click="emit('reassign', allocation.id)"
      >
        change
      </button>
    </div>

    <!-- Amount -->
    <div class="mt-1 flex items-center gap-2">
      <template v-if="editingAmount">
        <input
          v-model="amountInput"
          type="text"
          inputmode="decimal"
          class="w-28 border-b border-accent-border bg-transparent font-mono text-input font-medium text-fg outline-none"
          @blur="commitEdit"
          @keydown.enter="commitEdit"
        />
      </template>
      <template v-else>
        <button type="button" class="hover:underline" @click="startEdit">
          <MoneyAmount :amount="allocation.amount" size="md" />
        </button>
      </template>
    </div>

    <!-- Budget balance after this allocation -->
    <div class="mt-1 flex items-center gap-2 text-meta text-fg-muted">
      <span class="flex-none">Budget balance after</span>
      <span class="min-w-0 flex-1 border-b border-dotted border-border" />
      <MoneyAmount
        class="flex-none"
        :amount="allocation.budgetBalance"
        size="sm"
      />
    </div>

    <!-- Category -->
    <div
      v-if="allocation.categoryFullName"
      class="mt-1 text-meta text-fg-muted"
    >
      {{ allocation.categoryFullName }}
    </div>
  </div>
</template>
