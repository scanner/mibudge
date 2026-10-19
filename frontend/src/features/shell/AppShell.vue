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
// It keeps the shell's own data current through the invalidation
// signal (`stores/invalidation.ts`): the bank-account list when any
// account may have changed, the Unallocated budget when the active
// account's budgets may have.  Pulling down from the top (touch) or
// the SideNav's Refresh button signals everything now.
//
// When the server reports a release other than this bundle's
// (`stores/release.ts`), a banner offers a page load, which gets the
// server's release.
//

// 3rd party imports
//
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

// app imports
//
import BottomNav from "@/components/layout/BottomNav.vue";
import PullIndicator from "@/components/layout/PullIndicator.vue";
import SideNav from "@/components/layout/SideNav.vue";
import TopBar from "@/components/layout/TopBar.vue";
import BaseBanner from "@/components/base/BaseBanner.vue";
import BaseButton from "@/components/base/BaseButton.vue";
import AccountSwitcher from "@/components/shared/AccountSwitcher.vue";
import { usePullToRefresh } from "@/composables/usePullToRefresh";
import type { AppRouteName } from "@/router/types";
import { useAccountContextStore } from "@/stores/accountContext";
import { useBudgetsStore } from "@/stores/budgets";
import { accountInterest, useInvalidationStore } from "@/stores/invalidation";
import { useReleaseStore } from "@/stores/release";

////////////////////////////////////////////////////////////////////////
//
const ctx = useAccountContextStore();
const budgets = useBudgetsStore();
const release = useReleaseStore();
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
const unallocated = computed(
  () => budgets.byId(ctx.unallocatedBudgetId)?.balance ?? null,
);

// Load the Unallocated budget whenever the active account changes, so
// the balance shows without waiting for a view to load it.  A failure
// leaves the placeholder; the page's own load reports errors.
//
watch(
  () => ctx.unallocatedBudgetId,
  (id) => {
    if (id && !budgets.byId(id))
      void budgets.fetchOne(id).catch(() => undefined);
  },
  { immediate: true },
);

////////////////////////////////////////////////////////////////////////
//
const invalidation = useInvalidationStore();

invalidation.onInvalidate(
  () => ({ kinds: ["bankAccounts"] }),
  () => ctx.refresh(),
);
invalidation.onInvalidate(
  () => accountInterest(ctx.activeBankAccountId, ["budgets"]),
  () => {
    const id = ctx.unallocatedBudgetId;
    return id ? budgets.fetchOne(id) : undefined;
  },
);

const pull = usePullToRefresh(() => invalidation.invalidate());
const buttonRefreshing = ref(false);

async function refreshNow() {
  buttonRefreshing.value = true;
  try {
    await invalidation.invalidate();
  } finally {
    buttonRefreshing.value = false;
  }
}

////////////////////////////////////////////////////////////////////////
//
// A detail page shows one record of the active account.  Switching
// accounts there moves to that section's list for the new account.
//
const LIST_FOR_DETAIL: Partial<Record<AppRouteName, AppRouteName>> = {
  "budget-detail": "budgets",
  "transaction-detail": "transactions",
};

function selectAccount(id: string) {
  const changed = id !== ctx.activeBankAccountId;
  ctx.setActive(id);
  switcherOpen.value = false;
  const list = LIST_FOR_DETAIL[route.name as AppRouteName];
  if (changed && list) void router.push({ name: list });
}

function reloadPage() {
  window.location.reload();
}

function manageAccounts() {
  switcherOpen.value = false;
  router.push({ name: "account" });
}
</script>

<template>
  <div class="flex min-h-screen bg-canvas">
    <SideNav
      :refreshing="buttonRefreshing || pull.refreshing.value"
      @refresh="refreshNow"
    />
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
      <PullIndicator
        :distance="pull.distance.value"
        :ready="pull.ready.value"
        :refreshing="pull.refreshing.value"
      />
      <main class="flex-1 px-page-x pb-4">
        <BaseBanner
          v-if="release.updateAvailable"
          class="mt-3 flex items-center justify-between gap-3"
        >
          <span>A new version of mibudge is available.</span>
          <BaseButton variant="secondary" size="sm" @click="reloadPage">
            Reload
          </BaseButton>
        </BaseBanner>
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
