<script setup lang="ts">
//
// BudgetPickerSheet — bottom sheet / modal for selecting a budget.
// Used when assigning a transaction allocation to a budget.
// Includes fzf substring search for filtering the budget list.
//

// 3rd party imports
//
import { Fzf } from "fzf";
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

// app imports
//
import MoneyAmount from "@/components/shared/MoneyAmount.vue";
import type { Budget } from "@/types/api";

////////////////////////////////////////////////////////////////////////
//
const props = defineProps<{
  open: boolean;
  budgets: Budget[];
  unallocatedBudgetId?: string | null;
}>();

const emit = defineEmits<{
  (e: "select", budget: Budget): void;
  (e: "cancel"): void;
}>();

////////////////////////////////////////////////////////////////////////
//
const query = ref("");

const visibleBudgets = computed(() => {
  const unallocId = props.unallocatedBudgetId;
  const list = props.budgets.filter(
    (b) => b.id !== unallocId && b.budget_type !== "A" && !b.archived,
  );

  const q = query.value.trim();
  if (!q) return list;

  const fzf = new Fzf(list, {
    selector: (b: Budget) => b.name,
    casing: "case-insensitive",
    fuzzy: false,
  });
  return fzf.find(q).map((r) => r.item);
});

////////////////////////////////////////////////////////////////////////
//
function onKey(e: KeyboardEvent) {
  if (!props.open) return;
  if (e.key === "Escape") emit("cancel");
}

function onSearchKeydown(e: KeyboardEvent) {
  if (e.key === "Enter" && visibleBudgets.value.length === 1) {
    emit("select", visibleBudgets.value[0]);
  }
}

const searchInput = ref<HTMLInputElement | null>(null);

onMounted(() => window.addEventListener("keydown", onKey));
onBeforeUnmount(() => window.removeEventListener("keydown", onKey));

watch(
  () => props.open,
  (isOpen) => {
    document.body.style.overflow = isOpen ? "hidden" : "";
    if (isOpen) {
      nextTick(() => searchInput.value?.focus());
    } else {
      query.value = "";
    }
  },
);
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="open" class="fixed inset-0 z-50 flex items-end justify-center md:items-center">
        <div class="absolute inset-0 bg-neutral-900/40" @click="emit('cancel')" />
        <div
          class="relative flex max-h-[70vh] w-full flex-col rounded-t-2xl bg-white shadow-xl md:w-[420px] md:rounded-card"
          role="dialog"
          aria-modal="true"
        >
          <!-- Header -->
          <div class="flex items-center justify-between border-b border-neutral-200 px-5 pb-3 pt-5">
            <h2 class="text-base font-medium text-neutral-900">Select budget</h2>
            <button
              type="button"
              class="text-sm text-neutral-500 hover:text-neutral-700"
              @click="emit('cancel')"
            >
              Cancel
            </button>
          </div>

          <!-- Search -->
          <div class="border-b border-neutral-100 px-5 py-2">
            <input
              ref="searchInput"
              v-model="query"
              type="text"
              placeholder="Search budgets…"
              class="w-full rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-1.5 text-sm text-neutral-900 outline-none placeholder:text-neutral-400 focus:border-ocean-400"
              @keydown="onSearchKeydown"
            />
          </div>

          <!-- Budget list -->
          <div class="flex-1 overflow-y-auto px-2 py-2">
            <button
              v-for="budget in visibleBudgets"
              :key="budget.id"
              type="button"
              class="flex w-full items-center justify-between rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-neutral-50"
              @click="emit('select', budget)"
            >
              <span class="text-sm font-medium text-neutral-900">{{ budget.name }}</span>
              <MoneyAmount :amount="budget.balance" :currency="budget.balance_currency" size="sm" />
            </button>

            <p
              v-if="visibleBudgets.length === 0"
              class="px-3 py-6 text-center text-sm text-neutral-500"
            >
              {{ query ? "No matching budgets." : "No budgets available." }}
            </p>
          </div>
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
