<script setup lang="ts">
//
// AccountSwitcher — bottom sheet listing the user's bank accounts.
// Selecting one updates the accountContext store; a "Manage accounts"
// link at the bottom navigates to the Account tab (UI_SPEC §5.4).
//

// 3rd party imports
//
import { IconCheck, IconChevronRight } from "@tabler/icons-vue";
import { onBeforeUnmount, onMounted, watch } from "vue";
import { useRouter } from "vue-router";

// app imports
//
import MoneyAmount from "./MoneyAmount.vue";
import { useAccountContextStore } from "@/stores/accountContext";

////////////////////////////////////////////////////////////////////////
//
interface Props {
  open: boolean;
}

const props = defineProps<Props>();
const emit = defineEmits<{ (event: "close"): void }>();

const ctx = useAccountContextStore();
const router = useRouter();

////////////////////////////////////////////////////////////////////////
//
function select(id: string) {
  ctx.setActive(id);
  emit("close");
}

function manage() {
  emit("close");
  router.push("/account/");
}

////////////////////////////////////////////////////////////////////////
//
function onKey(e: KeyboardEvent) {
  if (e.key === "Escape" && props.open) emit("close");
}
onMounted(() => window.addEventListener("keydown", onKey));
onBeforeUnmount(() => window.removeEventListener("keydown", onKey));

watch(
  () => props.open,
  (isOpen) => {
    document.body.style.overflow = isOpen ? "hidden" : "";
  },
);
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div
        v-if="open"
        class="fixed inset-0 z-40 flex items-end justify-center md:items-start md:pt-20"
      >
        <div class="absolute inset-0 bg-neutral-900/40" @click="emit('close')" />
        <div
          class="relative max-h-[80vh] w-full overflow-y-auto rounded-t-2xl bg-white p-4 shadow-xl md:w-[420px] md:rounded-card"
          role="dialog"
          aria-modal="true"
          aria-label="Switch bank account"
        >
          <h2 class="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral-500">
            Your accounts
          </h2>
          <ul class="space-y-1">
            <li v-for="account in ctx.accounts" :key="account.id">
              <button
                type="button"
                class="flex w-full items-center gap-3 rounded-subcard px-3 py-3 text-left hover:bg-neutral-50"
                @click="select(account.id)"
              >
                <span class="h-2.5 w-2.5 flex-none rounded-full bg-ocean-400" />
                <div class="min-w-0 flex-1">
                  <div class="truncate text-[15px] font-medium text-neutral-900">
                    {{ account.name }}
                  </div>
                  <div class="text-xs text-neutral-500">
                    <MoneyAmount
                      :amount="account.posted_balance"
                      :currency="account.posted_balance_currency"
                      size="sm"
                    />
                  </div>
                </div>
                <IconCheck
                  v-if="account.id === ctx.activeBankAccountId"
                  class="h-5 w-5 flex-none text-ocean-400"
                />
              </button>
            </li>
          </ul>
          <button
            type="button"
            class="mt-3 flex w-full items-center justify-between rounded-subcard px-3 py-3 text-left text-sm font-medium text-ocean-600 hover:bg-ocean-50"
            @click="manage"
          >
            Manage accounts
            <IconChevronRight class="h-4 w-4" />
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
