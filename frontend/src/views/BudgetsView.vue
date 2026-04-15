<script setup lang="ts">
//
// Placeholder — filled in during Phase 3 (Budgets feature).
//

// 3rd party imports
//
import { IconPlus } from "@tabler/icons-vue";
import { useRouter } from "vue-router";

// app imports
//
import AppShell from "@/components/layout/AppShell.vue";

const router = useRouter();
</script>

<template>
  <AppShell>
    <template #action>
      <button
        type="button"
        class="flex h-10 w-10 items-center justify-center rounded-full text-neutral-700 hover:bg-neutral-100"
        aria-label="Create budget"
        @click="router.push('/budgets/create/')"
      >
        <IconPlus class="h-5 w-5" />
      </button>
    </template>
    <section class="mt-4">
      <h1 class="text-xl font-medium text-neutral-900">Budgets</h1>
      <p class="mt-2 text-sm text-neutral-500">Coming in Phase 3.</p>
    </section>
  </AppShell>
</template>
