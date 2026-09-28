<script setup lang="ts">
//
// AllocationCard — renders a single allocation within a transaction
// detail view.  Shows budget name, editable amount, and category.
// Its delete button is always visible on touch screens, and appears on
// hover or keyboard focus with a pointer.
//

// 3rd party imports
//
import { IconTrash } from "@tabler/icons-vue";
import { computed, ref, watch } from "vue";

// app imports
//
import MoneyAmount from "@/components/base/MoneyAmount.vue";
import { toDecimal } from "@/domain/money";
import type { Allocation } from "@/models/allocation";
import BaseButton from "@/components/base/BaseButton.vue";
import BaseIconButton from "@/components/base/BaseIconButton.vue";
import BaseCard from "@/components/base/BaseCard.vue";

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
  const cleaned = amountInput.value.replace(/[^0-9.-]/g, "");
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
  <BaseCard padded class="group relative">
    <!-- Remove button -->
    <BaseIconButton
      label="Remove allocation"
      size="sm"
      tone="danger"
      class="absolute right-2 top-2 can-hover:opacity-0 can-hover:focus-visible:opacity-100 can-hover:group-hover:opacity-100"
      @click="emit('remove', allocation.id)"
    >
      <IconTrash class="size-icon-xs" />
    </BaseIconButton>

    <!-- Budget name + reassign -->
    <div class="flex items-center gap-2">
      <BaseButton
        v-if="budgetId"
        variant="link"
        @click="emit('navigate-budget', budgetId)"
      >
        {{ budgetName }}
      </BaseButton>
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
  </BaseCard>
</template>
