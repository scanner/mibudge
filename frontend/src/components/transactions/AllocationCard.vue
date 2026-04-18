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
import type { TransactionAllocation } from "@/types/api";

////////////////////////////////////////////////////////////////////////
//
const props = defineProps<{
  allocation: TransactionAllocation;
  budgetName: string;
  isOnly: boolean;
  currency: string;
}>();

const emit = defineEmits<{
  (e: "update", id: string, amount: string): void;
  (e: "delete", id: string): void;
  (e: "navigate-budget", budgetId: string): void;
}>();

////////////////////////////////////////////////////////////////////////
//
const editingAmount = ref(false);
const amountInput = ref(props.allocation.amount);

watch(
  () => props.allocation.amount,
  (v) => {
    amountInput.value = v;
  },
);

function startEdit() {
  editingAmount.value = true;
}

function commitEdit() {
  editingAmount.value = false;
  const cleaned = amountInput.value.replace(/[^0-9.\-]/g, "");
  if (cleaned && cleaned !== props.allocation.amount) {
    emit("update", props.allocation.id, cleaned);
  } else {
    amountInput.value = props.allocation.amount;
  }
}

////////////////////////////////////////////////////////////////////////
//
const budgetId = computed(() => props.allocation.budget);
</script>

<template>
  <div class="group relative rounded-card border border-neutral-200 bg-white px-4 py-3">
    <!-- Delete button (hover on desktop, always visible would be via swipe on mobile) -->
    <button
      v-if="!isOnly"
      type="button"
      class="absolute right-2 top-2 flex h-6 w-6 items-center justify-center rounded-full text-neutral-400 opacity-0 transition-opacity hover:bg-coral-50 hover:text-coral-600 group-hover:opacity-100"
      aria-label="Remove allocation"
      @click="emit('delete', allocation.id)"
    >
      <IconTrash class="h-3.5 w-3.5" />
    </button>

    <!-- Budget name -->
    <button
      v-if="budgetId"
      type="button"
      class="text-sm font-medium text-ocean-600 hover:underline"
      @click="emit('navigate-budget', budgetId)"
    >
      {{ budgetName }}
    </button>
    <span v-else class="text-sm italic text-neutral-500">Unallocated</span>

    <!-- Amount -->
    <div class="mt-1 flex items-center gap-2">
      <template v-if="editingAmount">
        <input
          v-model="amountInput"
          type="text"
          inputmode="decimal"
          class="w-28 border-b border-ocean-400 bg-transparent font-mono text-[15px] font-medium text-neutral-900 outline-none"
          @blur="commitEdit"
          @keydown.enter="commitEdit"
        />
      </template>
      <template v-else>
        <button type="button" class="hover:underline" @click="startEdit">
          <MoneyAmount :amount="allocation.amount" :currency="currency" size="md" />
        </button>
      </template>
    </div>

    <!-- Category -->
    <div v-if="allocation.category" class="mt-1 text-xs text-neutral-500">
      {{ allocation.category }}
    </div>
  </div>
</template>
