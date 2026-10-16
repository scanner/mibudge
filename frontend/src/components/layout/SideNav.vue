<script setup lang="ts">
//
// SideNav — vertical navigation for ≥md breakpoints.  Shown alongside
// the main content; collapses to icon-only on tablet (md..lg) and
// expands to icon + label on desktop (≥lg).
//
// Below the tabs, a Refresh button emits `refresh`; while `refreshing`
// it is disabled and its icon spins.  It is styled as one more nav row
// (a `Base*` button would not match the tabs beside it).  Touch screens also pull down to
// refresh (see AppShell).
//

// 3rd party imports
//
import {
  IconLayoutGrid,
  IconList,
  IconRefresh,
  IconUser,
  IconWallet,
} from "@tabler/icons-vue";
import type { Component } from "vue";

// app imports
//
import type { AppRouteName } from "@/router/types";

////////////////////////////////////////////////////////////////////////
//
interface TabDef {
  label: string;
  icon: Component;
  to: { name: AppRouteName };
}

defineProps<{ refreshing: boolean }>();

const emit = defineEmits<{
  (event: "refresh"): void;
}>();

const tabs: TabDef[] = [
  { label: "Overview", icon: IconLayoutGrid, to: { name: "overview" } },
  { label: "Budgets", icon: IconWallet, to: { name: "budgets" } },
  { label: "Transactions", icon: IconList, to: { name: "transactions" } },
  { label: "Account", icon: IconUser, to: { name: "account" } },
];
</script>

<template>
  <aside
    class="sticky top-0 hidden h-screen flex-col border-r border-border bg-surface md:flex md:w-16 lg:w-56"
    aria-label="Primary"
  >
    <div class="px-3 py-4 text-label font-semibold text-fg">
      <span class="hidden lg:inline">mibudge</span>
      <span class="lg:hidden">m</span>
    </div>
    <nav class="flex flex-col gap-1 px-2">
      <router-link
        v-for="tab in tabs"
        :key="tab.label"
        :to="tab.to"
        class="flex items-center gap-3 rounded-control px-3 py-2 text-body-sm text-fg-muted hover:bg-surface-sunken"
        active-class="bg-accent-subtle text-accent-fg"
      >
        <component :is="tab.icon" class="h-5 w-5 flex-none" />
        <span class="hidden lg:inline">{{ tab.label }}</span>
      </router-link>
      <button
        type="button"
        class="tap-target flex items-center gap-3 rounded-control px-3 py-2 text-body-sm text-fg-muted hover:bg-surface-sunken"
        aria-label="Refresh"
        :disabled="refreshing"
        @click="emit('refresh')"
      >
        <IconRefresh
          class="h-5 w-5 flex-none"
          :class="refreshing ? 'animate-spin' : ''"
        />
        <span class="hidden lg:inline">Refresh</span>
      </button>
    </nav>
  </aside>
</template>
