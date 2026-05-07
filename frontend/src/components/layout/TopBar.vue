<script setup lang="ts">
//
// TopBar — three-zone persistent header (UI_SPEC §3.2).
//
// Left: back button when history has depth, otherwise empty.
// Center: account context block — active account name + posted
//         balance (subdued) on top, unallocated amount (dominant) on
//         the next line.  Tappable → opens AccountSwitcher.
// Right: `action` slot — parent supplies route-appropriate button.
//

// 3rd party imports
//
import { IconChevronDown, IconChevronLeft } from "@tabler/icons-vue";
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

// app imports
//
import AccountSwitcher from "@/components/shared/AccountSwitcher.vue";
import MoneyAmount from "@/components/shared/MoneyAmount.vue";
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
// Back arrow: visible on any non-root route.  The root is /app/ which
// the router presents as "/" under base.
//
const showBack = computed(() => route.path !== "/");

function onBack() {
  // history.length === 1 when user opened the app directly on a deep
  // route — fall back to "/".
  if (window.history.length > 1) router.back();
  else router.push("/");
}

////////////////////////////////////////////////////////////////////////
//
const activeAccount = computed(() => ctx.activeBankAccount);

// Unallocated amount comes from the unallocated Budget object.  Until
// it's loaded (or if the active account has no unallocated budget
// yet), render "—" instead of a zero that might mislead.
//
const unallocated = computed(() => {
  const id = ctx.unallocatedBudgetId;
  if (!id) return null;
  return budgets.byId(id);
});

// Fetch the unallocated budget whenever the active account changes so
// TopBar always has a balance to display without waiting for a view to
// load it.
watch(
  () => ctx.unallocatedBudgetId,
  (id) => {
    if (id && !budgets.byId(id)) {
      budgets.fetchOne(id);
    }
  },
  { immediate: true },
);
</script>

<template>
  <header
    class="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-neutral-200 bg-white px-4"
  >
    <div class="flex w-10 justify-start">
      <button
        v-if="showBack"
        type="button"
        class="flex h-10 w-10 items-center justify-center rounded-full text-neutral-700 hover:bg-neutral-100"
        aria-label="Back"
        @click="onBack"
      >
        <IconChevronLeft class="h-5 w-5" />
      </button>
    </div>

    <button
      v-if="activeAccount"
      type="button"
      class="mx-2 flex min-w-0 flex-1 flex-col items-center text-center"
      aria-label="Switch bank account"
      @click="switcherOpen = true"
    >
      <span class="flex items-center gap-1 text-[11px] text-secondary">
        <span class="truncate">{{ activeAccount.name }}</span>
        <span class="whitespace-nowrap">
          ·
          <MoneyAmount
            :amount="activeAccount.posted_balance"
            :currency="activeAccount.posted_balance_currency"
            size="sm"
          />
        </span>
        <IconChevronDown class="h-3 w-3" />
      </span>
      <MoneyAmount
        v-if="unallocated"
        :amount="unallocated.balance"
        :currency="unallocated.balance_currency"
        size="lg"
      />
      <span v-else class="font-mono text-[22px] font-medium text-neutral-400">—</span>
      <span class="text-[10px] font-semibold uppercase tracking-wider text-mint-400">
        Unallocated
      </span>
    </button>
    <div v-else class="flex-1" />

    <div class="flex w-10 justify-end">
      <slot name="action" />
    </div>
  </header>

  <AccountSwitcher :open="switcherOpen" @close="switcherOpen = false" />
</template>
