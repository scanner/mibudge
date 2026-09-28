<script setup lang="ts">
//
// AccountSwitcher -- a BaseSheet listing the user's bank accounts.
// Presentational: emits `select` with the chosen account id, `manage`
// for the "Manage accounts" link, and `close`.
//

// 3rd party imports
//
import { IconCheck, IconChevronRight } from "@tabler/icons-vue";

// app imports
//
import MoneyAmount from "@/components/base/MoneyAmount.vue";
import BaseSheet from "@/components/base/BaseSheet.vue";
import type { BankAccount } from "@/models/bankAccount";
import BaseSectionHeader from "@/components/base/BaseSectionHeader.vue";

////////////////////////////////////////////////////////////////////////
//
interface Props {
  open: boolean;
  accounts: BankAccount[];
  activeId: string | null;
}

defineProps<Props>();
const emit = defineEmits<{
  (event: "close"): void;
  (event: "select", id: string): void;
  (event: "manage"): void;
}>();
</script>

<template>
  <BaseSheet
    :open="open"
    label="Switch bank account"
    align="top"
    @close="emit('close')"
  >
    <BaseSectionHeader title="Your accounts" class="mb-3" />
    <ul class="space-y-1">
      <li v-for="account in accounts" :key="account.id">
        <button
          type="button"
          class="flex w-full items-center gap-3 rounded-control px-3 py-3 text-left hover:bg-surface-sunken"
          @click="emit('select', account.id)"
        >
          <span class="h-2.5 w-2.5 flex-none rounded-pill bg-accent" />
          <div class="min-w-0 flex-1">
            <div class="truncate text-item-title text-fg">
              {{ account.name }}
            </div>
            <div class="text-meta text-fg-muted">
              <MoneyAmount :amount="account.postedBalance" size="sm" />
            </div>
          </div>
          <IconCheck
            v-if="account.id === activeId"
            class="size-icon-md flex-none text-accent-fg"
          />
        </button>
      </li>
    </ul>
    <button
      type="button"
      class="mt-3 flex w-full items-center justify-between rounded-control px-3 py-3 text-left text-label text-fg-link hover:bg-accent-subtle"
      @click="emit('manage')"
    >
      Manage accounts
      <IconChevronRight class="size-icon-sm" />
    </button>
  </BaseSheet>
</template>
