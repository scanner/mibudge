<script setup lang="ts">
//
// TopBar — three-zone persistent header (UI_SPEC §3.2).  Presentational:
// the shell passes the active account and its Unallocated budget in,
// and handles the `back` and `switch-account` events.
//
// Left: back button when `showBack` is set, otherwise empty.
// Center: account context block — active account name + available
//         balance (subdued) on top, unallocated amount (dominant) on
//         the next line.  Tapping it emits `switch-account`.
// Right: `action` slot — the view supplies a route-appropriate button.
//

// 3rd party imports
//
import { IconChevronDown, IconChevronLeft } from "@tabler/icons-vue";

// app imports
//
import MoneyAmount from "@/components/shared/MoneyAmount.vue";
import type { Money } from "@/domain/money";
import type { BankAccount } from "@/models/bankAccount";

////////////////////////////////////////////////////////////////////////
//
defineProps<{
  account: BankAccount | null;
  // `null` until the Unallocated budget is loaded; shown as "—" rather
  // than a zero that might mislead.
  unallocated: Money | null;
  showBack: boolean;
}>();

const emit = defineEmits<{
  (event: "back"): void;
  (event: "switch-account"): void;
}>();
</script>

<template>
  <header
    class="sticky top-0 z-nav flex h-topbar items-center justify-between border-b border-border bg-surface px-page-x"
  >
    <div class="flex w-10 justify-start">
      <button
        v-if="showBack"
        type="button"
        class="flex h-10 w-10 items-center justify-center rounded-pill text-fg-muted hover:bg-surface-muted"
        aria-label="Back"
        @click="emit('back')"
      >
        <IconChevronLeft class="size-icon-md" />
      </button>
    </div>

    <button
      v-if="account"
      type="button"
      class="mx-2 flex min-w-0 flex-1 flex-col items-center text-center"
      aria-label="Switch bank account"
      @click="emit('switch-account')"
    >
      <span class="flex items-center gap-1 text-meta text-fg-muted">
        <span class="truncate">{{ account.name }}, Available:</span>
        <MoneyAmount
          :amount="account.availableBalance"
          size="sm"
          class="whitespace-nowrap"
        />
        <IconChevronDown class="size-icon-xs flex-none" />
      </span>
      <span class="text-amount text-money-positive">
        Unallocated
        <MoneyAmount v-if="unallocated" :amount="unallocated" size="sm" />
        <span v-else class="font-mono text-fg-subtle">—</span>
      </span>
    </button>
    <div v-else class="flex-1" />

    <div class="flex w-10 justify-end">
      <slot name="action" />
    </div>
  </header>
</template>
