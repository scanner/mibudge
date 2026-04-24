<script setup lang="ts">
//
// BudgetCreateView — type selector + BudgetForm.  (UI_SPEC §4.4)
//
// On success navigates to the new budget's detail view.
//

// 3rd party imports
//
import { useRouter } from "vue-router";

// app imports
//
import BudgetForm from "@/components/budgets/BudgetForm.vue";
import AppShell from "@/components/layout/AppShell.vue";
import { useBudgetsStore } from "@/stores/budgets";
import type { Budget } from "@/types/api";

////////////////////////////////////////////////////////////////////////
//
const router = useRouter();
const store = useBudgetsStore();

function onSaved(budget: Budget) {
  store.upsert(budget);
  router.push(`/budgets/${budget.id}/`);
}
</script>

<template>
  <AppShell>
    <div class="mx-auto max-w-lg pt-4">
      <h1 class="mb-5 text-[22px] font-medium text-neutral-900">New budget</h1>
      <BudgetForm mode="create" @saved="onSaved" @cancel="router.push('/budgets/')" />
    </div>
  </AppShell>
</template>
