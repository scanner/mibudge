<script setup lang="ts">
//
// BottomNav — mobile tab bar (UI_SPEC §3.3).  Renders only at <md
// breakpoints; AppShell swaps to SideNav above that.
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

// The router base is "/app/", so all `to` values here are relative.
const tabs: TabDef[] = [
  { label: "Overview", icon: IconLayoutGrid, to: "/" },
  { label: "Budgets", icon: IconWallet, to: "/budgets/" },
  { label: "Transactions", icon: IconList, to: "/transactions/" },
  { label: "Account", icon: IconUser, to: "/account/" },
];
</script>

<template>
  <nav
    class="sticky bottom-0 z-20 flex h-16 items-stretch justify-around border-t border-neutral-200 bg-white md:hidden"
    aria-label="Primary"
  >
    <router-link
      v-for="tab in tabs"
      :key="tab.to"
      :to="tab.to"
      class="flex flex-1 flex-col items-center justify-center gap-1 text-[11px] text-neutral-500"
      active-class="text-ocean-400"
    >
      <component :is="tab.icon" class="h-5 w-5" />
      {{ tab.label }}
    </router-link>
  </nav>
</template>
