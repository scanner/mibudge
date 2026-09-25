<script setup lang="ts">
//
// AppShell — authenticated layout.  Mobile: TopBar + content +
// BottomNav.  Tablet/Desktop: SideNav on the left, TopBar + content on
// the right.  The shell provides a slot for the page content; each
// view opts in to a nav-right action via the `action` named slot.
//
// The shell is the container for the presentational TopBar and
// AccountSwitcher: it reads the account context and the budgets cache,
// loads the active account's Unallocated budget, and handles back
// navigation and account switching.
//

// 3rd party imports
//
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

// app imports
//
import BottomNav from "@/components/layout/BottomNav.vue";
import SideNav from "@/components/layout/SideNav.vue";
import TopBar from "@/components/layout/TopBar.vue";
import AccountSwitcher from "@/components/shared/AccountSwitcher.vue";
import { useAccountContextStore } from "@/stores/accountContext";
import { useBudgetsStore } from "@/stores/budgets";

////////////////////////////////////////////////////////////////////////
//
const ctx = useAccountContextStore();
const budgets = useBudgetsStore();
const route = useRoute();
const router = useRouter();

const switcherOpen = ref(false);

////////////////////////////////////////////////////////////////////////
//
// Back arrow: visible on any non-root route.  History length 1 means
// the app was opened directly on a deep route; go to the overview.
//
const showBack = computed(() => route.path !== "/");

function onBack() {
  if (window.history.length > 1) router.back();
  else router.push({ name: "overview" });
}

////////////////////////////////////////////////////////////////////////
//
const unallocated = computed(() => budgets.byId(ctx.unallocatedBudgetId)?.balance ?? null);

// Load the Unallocated budget whenever the active account changes, so
// the balance shows without waiting for a view to load it.
//
watch(
  () => ctx.unallocatedBudgetId,
  (id) => {
    if (id && !budgets.byId(id)) void budgets.fetchOne(id).catch(() => undefined);
  },
  { immediate: true },
);

////////////////////////////////////////////////////////////////////////
//
function selectAccount(id: string) {
  ctx.setActive(id);
  switcherOpen.value = false;
}

function manageAccounts() {
  switcherOpen.value = false;
  router.push({ name: "account" });
}
</script>

<template>
  <div class="flex min-h-screen bg-neutral-50">
    <SideNav />
    <div class="flex min-w-0 flex-1 flex-col">
      <TopBar
        :account="ctx.activeBankAccount"
        :unallocated="unallocated"
        :show-back="showBack"
        @back="onBack"
        @switch-account="switcherOpen = true"
      >
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

  <AccountSwitcher
    :open="switcherOpen"
    :accounts="ctx.accounts"
    :active-id="ctx.activeBankAccountId"
    @close="switcherOpen = false"
    @select="selectAccount"
    @manage="manageAccounts"
  />
</template>
