<script setup lang="ts">
//
// AppShell — authenticated layout.  Mobile: TopBar + content +
// BottomNav.  Tablet/Desktop: SideNav on the left, TopBar + content on
// the right.  The shell provides a slot for the page content; each
// view opts in to a nav-right action via the `action` named slot.
//

// app imports
//
import BottomNav from "./BottomNav.vue";
import SideNav from "./SideNav.vue";
import TopBar from "./TopBar.vue";
</script>

<template>
  <div class="flex min-h-screen bg-neutral-50">
    <SideNav />
    <div class="flex min-w-0 flex-1 flex-col">
      <TopBar>
        <template #action>
          <slot name="action" />
        </template>
      </TopBar>
      <main class="flex-1 px-4 pb-4">
        <slot />
      </main>
      <BottomNav />
    </div>
  </div>
</template>
