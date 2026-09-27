<script setup lang="ts">
//
// AccountSwitcher — bottom sheet listing the user's bank accounts
// (UI_SPEC §5.4).  Presentational: emits `select` with the chosen
// account id, `manage` for the "Manage accounts" link, and `close`.
// `useModal` provides the scroll lock, Escape-to-close and focus
// return.
//

// 3rd party imports
//
import { IconCheck, IconChevronRight } from "@tabler/icons-vue";

// app imports
//
import MoneyAmount from "./MoneyAmount.vue";
import { useModal } from "@/composables/useModal";
import type { BankAccount } from "@/models/bankAccount";

////////////////////////////////////////////////////////////////////////
//
interface Props {
  open: boolean;
  accounts: BankAccount[];
  activeId: string | null;
}

const props = defineProps<Props>();
const emit = defineEmits<{
  (event: "close"): void;
  (event: "select", id: string): void;
  (event: "manage"): void;
}>();

////////////////////////////////////////////////////////////////////////
//
useModal(
  () => props.open,
  () => emit("close"),
);
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div
        v-if="open"
        class="fixed inset-0 z-sheet flex items-end justify-center md:items-start md:pt-20"
      >
        <div class="absolute inset-0 bg-scrim/40" @click="emit('close')" />
        <div
          class="relative max-h-sheet w-full overflow-y-auto rounded-t-card bg-surface p-4 shadow-overlay md:w-sheet md:rounded-card"
          role="dialog"
          aria-modal="true"
          aria-label="Switch bank account"
        >
          <h2 class="mb-3 text-overline uppercase text-fg-muted">
            Your accounts
          </h2>
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
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 120ms ease-out;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
