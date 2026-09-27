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
        <div class="absolute inset-0 bg-scrim/40" @click="emit('close')" />
        <div
          class="relative w-full rounded-t-2xl bg-surface p-5 shadow-xl md:w-[480px] md:rounded-card"
        >
          <h2 class="mb-4 text-[18px] font-medium text-fg">Move money</h2>

          <div class="space-y-3">
            <div>
              <label class="mb-1 block text-[13px] font-medium text-fg"
                >Direction</label
              >
              <div class="flex rounded-subcard border border-border">
                <button
                  type="button"
                  class="flex-1 rounded-l-subcard py-2.5 text-sm font-medium transition-colors"
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
                  class="flex-1 rounded-r-subcard py-2.5 text-sm font-medium transition-colors"
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
              <label class="mb-1 block text-[13px] font-medium text-fg"
                >This budget</label
              >
              <div class="flex rounded-subcard border border-border">
                <button
                  type="button"
                  class="flex-1 rounded-l-subcard py-2.5 text-sm font-medium transition-colors"
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
                  class="flex-1 rounded-r-subcard py-2.5 text-sm font-medium transition-colors"
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
              <label class="mb-1 block text-[13px] font-medium text-fg">
                {{ moveDirection === "outof" ? "To" : "From" }}
              </label>
              <select
                v-model="moveOtherId"
                class="w-full rounded-subcard border border-border-strong px-3 py-2.5 text-sm text-fg"
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
              <label class="mb-1 block text-[13px] font-medium text-fg"
                >Amount</label
              >
              <input
                ref="moveAmountInput"
                v-model="moveAmount"
                type="number"
                min="0.01"
                step="0.01"
                placeholder="0.00"
                class="w-full rounded-subcard border border-border-strong px-3 py-2.5 font-mono text-[15px] text-fg focus:border-border-focus focus:outline-none"
                @keydown.enter="canSubmit && submitMove()"
              />
            </div>

            <p v-if="moveError" class="text-sm text-danger-fg">
              {{ moveError }}
            </p>

            <div class="flex gap-2 pt-1">
              <button
                type="button"
                class="flex-1 rounded-full border border-border py-3 text-sm font-medium text-fg hover:bg-surface-sunken"
                @click="emit('close')"
              >
                Cancel
              </button>
              <button
                type="button"
                :disabled="!canSubmit"
                class="flex-1 rounded-full py-3 text-sm font-medium text-fg-on-accent transition-colors"
                :class="
                  canSubmit
                    ? 'bg-accent hover:bg-accent-hover'
                    : 'cursor-not-allowed bg-surface-strong'
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
