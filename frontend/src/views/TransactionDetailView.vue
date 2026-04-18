<script setup lang="ts">
//
// TransactionDetailView — detail page for a single transaction.
// (UI_SPEC §4.6)
//
// Transactions are read-only imports.  Mutable fields: description,
// memo, image, document.  Allocations have full CRUD.
//

// 3rd party imports
//
import { IconArrowLeft, IconPlus } from "@tabler/icons-vue";
import Decimal from "decimal.js";
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

// app imports
//
import AllocationCard from "@/components/transactions/AllocationCard.vue";
import AppShell from "@/components/layout/AppShell.vue";
import MoneyAmount from "@/components/shared/MoneyAmount.vue";
import {
  createAllocation,
  deleteAllocation,
  listAllocations,
  updateAllocation,
} from "@/api/allocations";
import { getTransaction, updateTransaction, uploadTransactionAttachment } from "@/api/transactions";
import { useAccountContextStore } from "@/stores/accountContext";
import { useBudgetsStore } from "@/stores/budgets";
import { TRANSACTION_TYPE_LABELS } from "@/types/api";
import type { Transaction, TransactionAllocation } from "@/types/api";

////////////////////////////////////////////////////////////////////////
//
const route = useRoute();
const router = useRouter();
const ctx = useAccountContextStore();
const budgets = useBudgetsStore();

////////////////////////////////////////////////////////////////////////
//
const transaction = ref<Transaction | null>(null);
const allocations = ref<TransactionAllocation[]>([]);
const loading = ref(false);
const error = ref<string | null>(null);

////////////////////////////////////////////////////////////////////////
//
// Editable fields with debounced autosave.
//
const description = ref("");
const memo = ref("");
let memoDebounce: ReturnType<typeof setTimeout> | null = null;
let descDebounce: ReturnType<typeof setTimeout> | null = null;

////////////////////////////////////////////////////////////////////////
//
const txId = computed(() => route.params.id as string);

const partyName = computed(() => {
  const tx = transaction.value;
  if (!tx) return "";
  return tx.party || tx.description || tx.raw_description;
});

const typeLabel = computed(() => {
  const t = transaction.value?.transaction_type;
  if (!t) return "";
  return TRANSACTION_TYPE_LABELS[t] ?? t;
});

const formattedDate = computed(() => {
  const tx = transaction.value;
  if (!tx) return "";
  const d = new Date(tx.transaction_date + "T00:00:00");
  return d.toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  });
});

const accountName = computed(() => {
  return ctx.activeBankAccount?.name ?? "";
});

////////////////////////////////////////////////////////////////////////
//
// Allocation status indicator.
//
const allocationStatus = computed<{
  label: string;
  amount: string;
  bg: string;
  text: string;
}>(() => {
  const tx = transaction.value;
  if (!tx) return { label: "", amount: "0.00", bg: "", text: "" };

  const txAmount = new Decimal(tx.amount).abs();
  const unallocId = ctx.unallocatedBudgetId;
  const realAllocations = allocations.value.filter(
    (a) => a.budget !== null && a.budget !== unallocId,
  );
  const allocated = realAllocations.reduce(
    (sum, a) => sum.plus(new Decimal(a.amount).abs()),
    new Decimal(0),
  );
  const diff = txAmount.minus(allocated);

  if (realAllocations.length > 0 && diff.isZero()) {
    return {
      label: "Fully allocated",
      amount: txAmount.toFixed(2),
      bg: "bg-mint-50",
      text: "text-mint-600",
    };
  } else if (diff.greaterThan(0)) {
    return {
      label: "Unassigned",
      amount: diff.toFixed(2),
      bg: "bg-ocean-50",
      text: "text-ocean-600",
    };
  } else {
    return {
      label: "Over by",
      amount: diff.abs().toFixed(2),
      bg: "bg-coral-50",
      text: "text-coral-600",
    };
  }
});

const remaining = computed(() => {
  const tx = transaction.value;
  if (!tx) return "0.00";
  const txAmount = new Decimal(tx.amount).abs();
  const unallocId = ctx.unallocatedBudgetId;
  const allocated = allocations.value
    .filter((a) => a.budget !== null && a.budget !== unallocId)
    .reduce((sum, a) => sum.plus(new Decimal(a.amount).abs()), new Decimal(0));
  return txAmount.minus(allocated).toFixed(2);
});

////////////////////////////////////////////////////////////////////////
//
// Budget name helpers.
//
const visibleAllocations = computed(() => {
  const unallocId = ctx.unallocatedBudgetId;
  return allocations.value.filter((a) => a.budget !== null && a.budget !== unallocId);
});

function budgetName(budgetId: string | null): string {
  if (!budgetId) return "Unallocated";
  return budgets.byId(budgetId)?.name ?? "Budget";
}

////////////////////////////////////////////////////////////////////////
//
// Data loading.
//
async function load() {
  const id = txId.value;
  if (!id) return;
  loading.value = true;
  error.value = null;
  try {
    const [tx, allocPage] = await Promise.all([
      getTransaction(id),
      listAllocations({ transaction: id }),
    ]);
    transaction.value = tx;
    allocations.value = allocPage.results;
    description.value = tx.description;
    memo.value = tx.memo ?? "";

    // Ensure budgets are cached for name lookups.
    if (ctx.activeBankAccountId) {
      await budgets.fetchList({ bank_account: ctx.activeBankAccountId });
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Failed to load transaction.";
  } finally {
    loading.value = false;
  }
}

watch(txId, load, { immediate: true });

////////////////////////////////////////////////////////////////////////
//
// Autosave description (800ms debounce).
//
function onDescriptionInput() {
  if (descDebounce) clearTimeout(descDebounce);
  descDebounce = setTimeout(async () => {
    const id = txId.value;
    if (!id || description.value === transaction.value?.description) return;
    try {
      const updated = await updateTransaction(id, { description: description.value });
      transaction.value = updated;
    } catch {
      // Revert on failure.
      description.value = transaction.value?.description ?? "";
    }
  }, 800);
}

////////////////////////////////////////////////////////////////////////
//
// Autosave memo (800ms debounce).
//
function onMemoInput() {
  if (memoDebounce) clearTimeout(memoDebounce);
  memoDebounce = setTimeout(async () => {
    const id = txId.value;
    const newMemo = memo.value || null;
    if (!id || newMemo === (transaction.value?.memo ?? null)) return;
    try {
      const updated = await updateTransaction(id, { memo: memo.value || undefined });
      transaction.value = updated;
    } catch {
      memo.value = transaction.value?.memo ?? "";
    }
  }, 800);
}

////////////////////////////////////////////////////////////////////////
//
// Allocation CRUD.
//
async function onUpdateAllocation(id: string, amount: string) {
  try {
    const updated = await updateAllocation(id, { amount });
    const idx = allocations.value.findIndex((a) => a.id === id);
    if (idx !== -1) allocations.value[idx] = updated;
  } catch {
    // Reload on error.
    const page = await listAllocations({ transaction: txId.value });
    allocations.value = page.results;
  }
}

async function onDeleteAllocation(id: string) {
  try {
    await deleteAllocation(id);
    allocations.value = allocations.value.filter((a) => a.id !== id);
  } catch {
    // Reload on error.
    const page = await listAllocations({ transaction: txId.value });
    allocations.value = page.results;
  }
}

async function onAddSplit() {
  const tx = transaction.value;
  if (!tx) return;
  try {
    const alloc = await createAllocation({
      transaction: tx.id,
      budget: null,
      amount: remaining.value,
    });
    allocations.value = [...allocations.value, alloc];
  } catch {
    const page = await listAllocations({ transaction: txId.value });
    allocations.value = page.results;
  }
}

////////////////////////////////////////////////////////////////////////
//
// Attachments.
//
function onAttach(field: "image" | "document") {
  const input = document.createElement("input");
  input.type = "file";
  input.accept = field === "image" ? "image/*" : "*/*";
  input.onchange = async () => {
    const file = input.files?.[0];
    if (!file || !txId.value) return;
    try {
      const updated = await uploadTransactionAttachment(txId.value, field, file);
      transaction.value = updated;
    } catch {
      // Silent failure — user can retry.
    }
  };
  input.click();
}

function navigateBudget(budgetId: string) {
  router.push(`/budgets/${budgetId}/`);
}
</script>

<template>
  <AppShell>
    <template #action>
      <button
        type="button"
        class="flex h-10 w-10 items-center justify-center rounded-full text-neutral-700 hover:bg-neutral-100"
        aria-label="Back"
        @click="router.back()"
      >
        <IconArrowLeft class="h-5 w-5" />
      </button>
    </template>

    <!-- Loading -->
    <div v-if="loading" class="space-y-4 pt-6">
      <div class="h-8 w-48 animate-pulse rounded bg-neutral-100" />
      <div class="h-12 w-32 animate-pulse rounded bg-neutral-100" />
      <div class="h-4 w-64 animate-pulse rounded bg-neutral-100" />
    </div>

    <!-- Error -->
    <div v-else-if="error" class="rounded-card bg-coral-50 px-4 py-3 text-sm text-coral-600">
      {{ error }}
    </div>

    <template v-else-if="transaction">
      <!-- Hero block -->
      <section class="pb-4 pt-2 text-center">
        <h1 class="text-lg font-medium text-neutral-900">{{ partyName }}</h1>
        <MoneyAmount
          :amount="transaction.amount"
          :currency="transaction.amount_currency"
          size="hero"
          coloured
          class="mt-1"
        />
        <div class="mt-1.5 flex items-center justify-center gap-2 text-xs text-neutral-500">
          <span>{{ formattedDate }}</span>
          <span
            v-if="transaction.pending"
            class="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-600"
          >
            PENDING
          </span>
          <span v-if="accountName">· {{ accountName }}</span>
        </div>
      </section>

      <!-- Metadata section -->
      <section class="space-y-3 border-t border-neutral-200 pt-4">
        <div>
          <label class="text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
            Description
          </label>
          <input
            v-model="description"
            type="text"
            class="mt-0.5 block w-full border-b border-transparent bg-transparent text-sm text-neutral-900 outline-none transition-colors focus:border-ocean-400"
            @input="onDescriptionInput"
          />
        </div>

        <div v-if="transaction.raw_description !== transaction.description">
          <label class="text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
            Raw description
          </label>
          <p class="mt-0.5 text-sm text-neutral-600">{{ transaction.raw_description }}</p>
        </div>

        <div v-if="typeLabel" class="flex items-center justify-between">
          <label class="text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
            Type
          </label>
          <span class="text-sm text-neutral-700">{{ typeLabel }}</span>
        </div>

        <div class="flex items-center justify-between">
          <label class="text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
            Balance after
          </label>
          <MoneyAmount
            :amount="transaction.bank_account_posted_balance"
            :currency="transaction.bank_account_posted_balance_currency"
            size="sm"
          />
        </div>
      </section>

      <!-- Allocations section -->
      <section class="mt-6">
        <h2 class="mb-2 text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
          Allocations
        </h2>

        <div v-if="visibleAllocations.length > 0" class="space-y-2">
          <AllocationCard
            v-for="alloc in visibleAllocations"
            :key="alloc.id"
            :allocation="alloc"
            :budget-name="budgetName(alloc.budget)"
            :is-only="visibleAllocations.length === 1"
            :currency="transaction.amount_currency"
            @update="onUpdateAllocation"
            @delete="onDeleteAllocation"
            @navigate-budget="navigateBudget"
          />
        </div>

        <!-- Allocation status indicator (only when real allocations exist) -->
        <div
          v-if="visibleAllocations.length > 0"
          class="mt-3 flex items-center justify-between rounded-lg px-3 py-2 text-sm font-medium"
          :class="[allocationStatus.bg, allocationStatus.text]"
        >
          <span>{{ allocationStatus.label }}</span>
          <MoneyAmount
            :amount="allocationStatus.amount"
            :currency="transaction.amount_currency"
            size="sm"
          />
        </div>

        <!-- Assign / add split button -->
        <button
          type="button"
          class="mt-3 flex w-full items-center justify-center gap-1.5 rounded-lg border border-dashed border-ocean-300 px-3 py-2 text-sm font-medium text-ocean-600 transition-colors hover:border-ocean-400 hover:bg-ocean-50"
          @click="onAddSplit"
        >
          <IconPlus class="h-4 w-4" />
          {{ visibleAllocations.length > 0 ? "Add split" : "Assign to budget" }}
        </button>
      </section>

      <!-- Memo -->
      <section class="mt-6">
        <label class="text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
          Memo
        </label>
        <textarea
          v-model="memo"
          rows="2"
          placeholder="Add a memo…"
          class="mt-1 block w-full resize-none rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-900 outline-none transition-colors placeholder:text-neutral-400 focus:border-ocean-400"
          @input="onMemoInput"
        />
      </section>

      <!-- Attachments -->
      <section class="mt-6 flex gap-3">
        <button
          type="button"
          class="flex-1 rounded-lg border border-neutral-200 px-3 py-2 text-center text-sm text-neutral-600 transition-colors hover:border-neutral-300 hover:bg-neutral-50"
          @click="onAttach('image')"
        >
          {{ transaction.image ? "Replace photo" : "Attach photo" }}
        </button>
        <button
          type="button"
          class="flex-1 rounded-lg border border-neutral-200 px-3 py-2 text-center text-sm text-neutral-600 transition-colors hover:border-neutral-300 hover:bg-neutral-50"
          @click="onAttach('document')"
        >
          {{ transaction.document ? "Replace document" : "Attach document" }}
        </button>
      </section>

      <!-- Footer -->
      <p class="mt-8 pb-4 text-center text-xs text-neutral-400">
        Transactions are imported from bank statements and cannot be created or deleted.
      </p>
    </template>
  </AppShell>
</template>
