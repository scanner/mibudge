<script setup lang="ts">
//
// BudgetCreateView — type selector + BudgetForm.  (UI_SPEC §4.4)
// Route shell; the form saves through the budgets store.
//
// On success navigates to the new budget's detail view.
//

// 3rd party imports
//
import { useRouter } from "vue-router";

// app imports
//
import BudgetForm from "@/features/budgets/BudgetForm.vue";
import AppShell from "@/features/shell/AppShell.vue";
import type { Budget } from "@/models/budget";

////////////////////////////////////////////////////////////////////////
//
const router = useRouter();

function onSaved(budget: Budget) {
  router.push({ name: "budget-detail", params: { id: budget.id } });
}
</script>

<template>
  <AppShell>
    <div class="mx-auto max-w-lg pt-4">
      <h1 class="mb-5 text-[22px] font-medium text-neutral-900">New budget</h1>
      <BudgetForm
        mode="create"
        @saved="onSaved"
        @cancel="router.push({ name: 'budgets' })"
      />
    </div>
  </AppShell>
</template>
