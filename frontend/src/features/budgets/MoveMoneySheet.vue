<script setup lang="ts">
//
// MoveMoneySheet — the "Move money" form: transfer between this budget
// (or its fill-up goal) and another budget of the account.  Feature
// component (budgets); state and the transfer live in `useMoveMoney`,
// and `useModal` provides the scroll lock, Escape-to-close and focus
// return.  Emits `close` when dismissed or after a transfer.
//

// 3rd party imports
//
import { nextTick, ref, watch } from "vue";

// app imports
//
import { useModal } from "@/composables/useModal";
import type { Budget } from "@/models/budget";
import { useMoveMoney } from "./useMoveMoney";

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

const moveAmountInput = ref<HTMLInputElement | null>(null);

useModal(
  () => props.open,
  () => emit("close"),
);

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
  <Teleport to="body">
    <Transition name="fade">
      <div
        v-if="open"
        class="fixed inset-0 z-40 flex items-end justify-center md:items-center"
      >
        <div
          class="absolute inset-0 bg-neutral-900/40"
          @click="emit('close')"
        />
        <div
          class="relative w-full rounded-t-2xl bg-white p-5 shadow-xl md:w-[480px] md:rounded-card"
        >
          <h2 class="mb-4 text-[18px] font-medium text-neutral-900">
            Move money
          </h2>

          <div class="space-y-3">
            <div>
              <label class="mb-1 block text-[13px] font-medium text-neutral-700"
                >Direction</label
              >
              <div class="flex rounded-subcard border border-neutral-200">
                <button
                  type="button"
                  class="flex-1 rounded-l-subcard py-2.5 text-sm font-medium transition-colors"
                  :class="
                    moveDirection === 'outof'
                      ? 'bg-ocean-400 text-white'
                      : 'text-secondary hover:bg-neutral-50'
                  "
                  @click="moveDirection = 'outof'"
                >
                  Out of this budget
                </button>
                <button
                  type="button"
                  class="flex-1 rounded-r-subcard py-2.5 text-sm font-medium transition-colors"
                  :class="
                    moveDirection === 'into'
                      ? 'bg-ocean-400 text-white'
                      : 'text-secondary hover:bg-neutral-50'
                  "
                  @click="moveDirection = 'into'"
                >
                  Into this budget
                </button>
              </div>
            </div>

            <div v-if="fillupBudget">
              <label class="mb-1 block text-[13px] font-medium text-neutral-700"
                >This budget</label
              >
              <div class="flex rounded-subcard border border-neutral-200">
                <button
                  type="button"
                  class="flex-1 rounded-l-subcard py-2.5 text-sm font-medium transition-colors"
                  :class="
                    !moveTargetFillup
                      ? 'bg-ocean-400 text-white'
                      : 'text-secondary hover:bg-neutral-50'
                  "
                  @click="setMoveTarget(false)"
                >
                  {{ budget?.name }}
                </button>
                <button
                  type="button"
                  class="flex-1 rounded-r-subcard py-2.5 text-sm font-medium transition-colors"
                  :class="
                    moveTargetFillup
                      ? 'bg-ocean-400 text-white'
                      : 'text-secondary hover:bg-neutral-50'
                  "
                  @click="setMoveTarget(true)"
                >
                  {{ fillupBudget.name }} (fill-up)
                </button>
              </div>
            </div>

            <div>
              <label
                class="mb-1 block text-[13px] font-medium text-neutral-700"
              >
                {{ moveDirection === "outof" ? "To" : "From" }}
              </label>
              <select
                v-model="moveOtherId"
                class="w-full rounded-subcard border border-neutral-200 px-3 py-2.5 text-sm text-neutral-900"
              >
                <option
                  v-for="b in movePickerBudgets"
                  :key="b.id"
                  :value="b.id"
                >
                  {{ budgetPickerLabel(b) }}
                </option>
              </select>
            </div>

            <div>
              <label class="mb-1 block text-[13px] font-medium text-neutral-700"
                >Amount</label
              >
              <input
                ref="moveAmountInput"
                v-model="moveAmount"
                type="number"
                min="0.01"
                step="0.01"
                placeholder="0.00"
                class="w-full rounded-subcard border border-neutral-200 px-3 py-2.5 font-mono text-[15px] text-neutral-900 focus:border-ocean-400 focus:outline-none"
                @keydown.enter="canSubmit && submitMove()"
              />
            </div>

            <p v-if="moveError" class="text-sm text-coral-600">
              {{ moveError }}
            </p>

            <div class="flex gap-2 pt-1">
              <button
                type="button"
                class="flex-1 rounded-full border border-neutral-200 py-3 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
                @click="emit('close')"
              >
                Cancel
              </button>
              <button
                type="button"
                :disabled="!canSubmit"
                class="flex-1 rounded-full py-3 text-sm font-medium text-white transition-colors"
                :class="
                  canSubmit
                    ? 'bg-ocean-400 hover:bg-ocean-600'
                    : 'cursor-not-allowed bg-neutral-300'
                "
                @click="submitMove"
              >
                {{ moveSaving ? "Transferring…" : "Transfer" }}
              </button>
            </div>
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
