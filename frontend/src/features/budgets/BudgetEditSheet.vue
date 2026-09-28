<script setup lang="ts">
//
// BudgetEditSheet -- full-screen BaseSheet holding the budget edit
// form.  Feature component (budgets).  Emits `saved` with the updated
// budget, and `close`.
//

// app imports
//
import BaseSheet from "@/components/base/BaseSheet.vue";
import type { Budget } from "@/models/budget";
import BudgetForm from "./BudgetForm.vue";

////////////////////////////////////////////////////////////////////////
//
defineProps<{ open: boolean; budget: Budget | null }>();

const emit = defineEmits<{
  (e: "close"): void;
  (e: "saved", budget: Budget): void;
}>();
</script>

<template>
  <BaseSheet
    :open="open && !!budget"
    title="Edit budget"
    fullscreen
    @close="emit('close')"
  >
    <BudgetForm
      v-if="budget"
      mode="edit"
      :budget="budget"
      @saved="emit('saved', $event)"
      @cancel="emit('close')"
    />
  </BaseSheet>
</template>
