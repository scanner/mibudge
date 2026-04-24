<script setup lang="ts">
//
// SideNav — vertical navigation for ≥md breakpoints.  Shown alongside
// the main content; collapses to icon-only on tablet (md..lg) and
// expands to icon + label on desktop (≥lg).  (UI_SPEC §3.3)
//

// 3rd party imports
//
import { IconLayoutGrid, IconList, IconUser, IconWallet } from "@tabler/icons-vue";
import type { Component } from "vue";

////////////////////////////////////////////////////////////////////////
//
interface TabDef {
  label: string;
  icon: Component;
  to: string;
}

const tabs: TabDef[] = [
  { label: "Overview", icon: IconLayoutGrid, to: "/" },
  { label: "Budgets", icon: IconWallet, to: "/budgets/" },
  { label: "Transactions", icon: IconList, to: "/transactions/" },
  { label: "Account", icon: IconUser, to: "/account/" },
];
</script>

<template>
  <aside
    class="sticky top-0 hidden h-screen flex-col border-r border-neutral-200 bg-white md:flex md:w-16 lg:w-56"
    aria-label="Primary"
  >
    <div class="px-3 py-4 text-sm font-semibold text-neutral-900">
      <span class="hidden lg:inline">mibudge</span>
      <span class="lg:hidden">m</span>
    </div>
    <nav class="flex flex-col gap-1 px-2">
      <router-link
        v-for="tab in tabs"
        :key="tab.to"
        :to="tab.to"
        class="flex items-center gap-3 rounded-subcard px-3 py-2 text-sm text-neutral-600 hover:bg-neutral-50"
        active-class="bg-ocean-50 text-ocean-600"
      >
        <component :is="tab.icon" class="h-5 w-5 flex-none" />
        <span class="hidden lg:inline">{{ tab.label }}</span>
      </router-link>
    </nav>
  </aside>
</template>
