<script setup lang="ts">
//
// BudgetEditSheet — full-page overlay holding the budget edit form.
// Feature component (budgets).  `useModal` provides the scroll lock,
// Escape-to-close and focus return.  Emits `saved` with the updated
// budget, and `close`.
//

// app imports
//
import { useModal } from "@/composables/useModal";
import type { Budget } from "@/models/budget";
import BudgetForm from "./BudgetForm.vue";

////////////////////////////////////////////////////////////////////////
//
const props = defineProps<{ open: boolean; budget: Budget | null }>();

const emit = defineEmits<{
  (e: "close"): void;
  (e: "saved", budget: Budget): void;
}>();

useModal(
  () => props.open && !!props.budget,
  () => emit("close"),
);
</script>

<template>
  <Teleport to="body">
    <Transition name="slide-up">
      <div
        v-if="open && budget"
        class="fixed inset-0 z-40 overflow-y-auto bg-neutral-50"
      >
        <div class="mx-auto max-w-lg px-4 pb-8 pt-4">
          <div class="mb-4 flex items-center justify-between">
            <h2 class="text-[18px] font-medium text-neutral-900">
              Edit budget
            </h2>
          </div>
          <BudgetForm
            mode="edit"
            :budget="budget"
            @saved="emit('saved', $event)"
            @cancel="emit('close')"
          />
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.slide-up-enter-active,
.slide-up-leave-active {
  transition: transform 250ms ease-out;
}
.slide-up-enter-from,
.slide-up-leave-to {
  transform: translateY(100%);
}
</style>
