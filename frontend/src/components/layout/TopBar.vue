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
    class="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-neutral-200 bg-white px-4"
  >
    <div class="flex w-10 justify-start">
      <button
        v-if="showBack"
        type="button"
        class="flex h-10 w-10 items-center justify-center rounded-full text-neutral-700 hover:bg-neutral-100"
        aria-label="Back"
        @click="emit('back')"
      >
        <IconChevronLeft class="h-5 w-5" />
      </button>
    </div>

    <button
      v-if="account"
      type="button"
      class="mx-2 flex min-w-0 flex-1 flex-col items-center text-center"
      aria-label="Switch bank account"
      @click="emit('switch-account')"
    >
      <span class="flex items-center gap-1 text-[11px] text-secondary">
        <span class="truncate">{{ account.name }}, Available:</span>
        <MoneyAmount
          :amount="account.availableBalance"
          size="sm"
          class="whitespace-nowrap"
        />
        <IconChevronDown class="h-3 w-3 flex-none" />
      </span>
      <span class="text-[14px] font-medium text-mint-600">
        Unallocated
        <MoneyAmount v-if="unallocated" :amount="unallocated" size="sm" />
        <span v-else class="font-mono text-neutral-400">—</span>
      </span>
    </button>
    <div v-else class="flex-1" />

    <div class="flex w-10 justify-end">
      <slot name="action" />
    </div>
  </header>
</template>
