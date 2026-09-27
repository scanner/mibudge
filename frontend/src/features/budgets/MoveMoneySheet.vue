<script setup lang="ts">
//
// MoveMoneySheet — the "Move money" form: transfer between this budget
// (or its fill-up goal) and another budget of the account.  Feature
// component (budgets) in a BaseSheet; state and the transfer live in
// `useMoveMoney`.  Emits `close` when dismissed or after a transfer.
//

// 3rd party imports
//
import { nextTick, ref, watch } from "vue";

// app imports
//
import BaseSheet from "@/components/base/BaseSheet.vue";
import type { Budget } from "@/models/budget";
import { useMoveMoney } from "./useMoveMoney";
import BaseButton from "@/components/base/BaseButton.vue";
import BaseInput from "@/components/base/BaseInput.vue";
import BaseSelect from "@/components/base/BaseSelect.vue";

////////////////////////////////////////////////////////////////////////
//
const props = defineProps<{
  open: boolean;
  budget: Budget | null;
  fillupBudget: Budget | null;
}>();

const emit = defineEmits<{ (e: "close"): void }>();

const {
  direction: moveDirection,
  targetFillup: moveTargetFillup,
  otherId: moveOtherId,
  amount: moveAmount,
  saving: moveSaving,
  error: moveError,
  pickerBudgets: movePickerBudgets,
  canSubmit,
  pickerLabel: budgetPickerLabel,
  prepare,
  setTarget: setMoveTarget,
  submit,
} = useMoveMoney(
  () => props.budget,
  () => props.fillupBudget,
);

const moveAmountInput = ref<{ focus(): void } | null>(null);

watch(
  () => props.open,
  async (isOpen) => {
    if (!isOpen) return;
    await prepare();
    await nextTick();
    moveAmountInput.value?.focus();
  },
  { immediate: true },
);

////////////////////////////////////////////////////////////////////////
//
async function submitMove() {
  if (await submit()) emit("close");
}
</script>

<template>
  <BaseSheet :open="open" title="Move money" @close="emit('close')">
    <div class="space-y-3">
      <div>
        <label class="mb-1 block text-label text-fg">Direction</label>
        <div class="flex rounded-control border border-border">
          <button
            type="button"
            class="flex-1 rounded-l-control py-2.5 text-label transition-colors"
            :class="
              moveDirection === 'outof'
                ? 'bg-accent text-fg-on-accent'
                : 'text-fg-muted hover:bg-surface-sunken'
            "
            @click="moveDirection = 'outof'"
          >
            Out of this budget
          </button>
          <button
            type="button"
            class="flex-1 rounded-r-control py-2.5 text-label transition-colors"
            :class="
              moveDirection === 'into'
                ? 'bg-accent text-fg-on-accent'
                : 'text-fg-muted hover:bg-surface-sunken'
            "
            @click="moveDirection = 'into'"
          >
            Into this budget
          </button>
        </div>
      </div>

      <div v-if="fillupBudget">
        <label class="mb-1 block text-label text-fg">This budget</label>
        <div class="flex rounded-control border border-border">
          <button
            type="button"
            class="flex-1 rounded-l-control py-2.5 text-label transition-colors"
            :class="
              !moveTargetFillup
                ? 'bg-accent text-fg-on-accent'
                : 'text-fg-muted hover:bg-surface-sunken'
            "
            @click="setMoveTarget(false)"
          >
            {{ budget?.name }}
          </button>
          <button
            type="button"
            class="flex-1 rounded-r-control py-2.5 text-label transition-colors"
            :class="
              moveTargetFillup
                ? 'bg-accent text-fg-on-accent'
                : 'text-fg-muted hover:bg-surface-sunken'
            "
            @click="setMoveTarget(true)"
          >
            {{ fillupBudget.name }} (fill-up)
          </button>
        </div>
      </div>

      <div>
        <label class="mb-1 block text-label text-fg">
          {{ moveDirection === "outof" ? "To" : "From" }}
        </label>
        <BaseSelect v-model="moveOtherId">
          <option v-for="b in movePickerBudgets" :key="b.id" :value="b.id">
            {{ budgetPickerLabel(b) }}
          </option>
        </BaseSelect>
      </div>

      <div>
        <label class="mb-1 block text-label text-fg">Amount</label>
        <BaseInput
          ref="moveAmountInput"
          v-model="moveAmount"
          type="number"
          min="0.01"
          step="0.01"
          placeholder="0.00"
          @keydown.enter="canSubmit && submitMove()"
          mono
        />
      </div>

      <p v-if="moveError" class="text-body-sm text-danger-fg">
        {{ moveError }}
      </p>

      <div class="flex gap-2 pt-1">
        <BaseButton variant="secondary" class="flex-1" @click="emit('close')">
          Cancel
        </BaseButton>
        <BaseButton :disabled="!canSubmit" class="flex-1" @click="submitMove">
          {{ moveSaving ? "Transferring…" : "Transfer" }}
        </BaseButton>
      </div>
    </div>
  </BaseSheet>
</template>
