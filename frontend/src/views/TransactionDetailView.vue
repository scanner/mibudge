<script setup lang="ts">
//
// TransactionDetailView — detail page for a single transaction.
// (UI_SPEC §4.6)  Route shell over `useTransactionDetail`.
//
// Transactions are read-only imports.  Mutable fields: description,
// memo, image, document (autosaved / uploaded).  Allocations are
// managed through the declarative splits endpoint.  ArrowUp /
// ArrowDown step to the previous / next row of the transaction list.
//

// 3rd party imports
//
import { IconArrowLeft, IconChevronDown, IconChevronUp } from "@tabler/icons-vue";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

// app imports
//
import AllocationsSection from "@/components/transactions/AllocationsSection.vue";
import SplitEditorDialog from "@/components/transactions/SplitEditorDialog.vue";
import TransactionHero from "@/components/transactions/TransactionHero.vue";
import MoneyAmount from "@/components/shared/MoneyAmount.vue";
import { isModalOpen } from "@/composables/useModal";
import { formatTxDateLong } from "@/domain/dates";
import { transactionTypeLabel } from "@/domain/labels";
import { displayName, occurredAt } from "@/models/transaction";
import type { AttachmentField } from "@/features/transactions/useTransactionDetail";
import { useTransactionDetail } from "@/features/transactions/useTransactionDetail";
import AppShell from "@/features/shell/AppShell.vue";
import { useAccountContextStore } from "@/stores/accountContext";
import { useSessionStore } from "@/stores/session";

////////////////////////////////////////////////////////////////////////
//
const props = defineProps<{ id: string }>();
const router = useRouter();
const ctx = useAccountContextStore();
const session = useSessionStore();

const {
  transaction,
  loading,
  error,
  description,
  memo,
  onDescriptionInput,
  onDescriptionBlur,
  onMemoInput,
  onMemoBlur,
  descriptionError,
  memoError,
  unallocatedBudgetId,
  visibleAllocations,
  coverage,
  initialSplits,
  accountBudgets,
  budgetName,
  applySplits,
  updateAllocation,
  removeAllocation,
  splitError,
  attachmentError,
  uploadAttachment,
  prevId: prevTxId,
  nextId: nextTxId,
} = useTransactionDetail(() => props.id);

const pickerOpen = ref(false);

////////////////////////////////////////////////////////////////////////
//
const partyName = computed(() => (transaction.value ? displayName(transaction.value) : ""));
const typeLabel = computed(() => transactionTypeLabel(transaction.value?.transactionType));
const formattedDate = computed(() =>
  transaction.value ? formatTxDateLong(occurredAt(transaction.value), session.timezone) : "",
);
const accountName = computed(() => ctx.activeBankAccount?.name ?? "");

////////////////////////////////////////////////////////////////////////
//
function goToPrev() {
  if (prevTxId.value)
    router.replace({ name: "transaction-detail", params: { id: prevTxId.value } });
}
function goToNext() {
  if (nextTxId.value)
    router.replace({ name: "transaction-detail", params: { id: nextTxId.value } });
}

function onKeyNav(e: KeyboardEvent) {
  if (pickerOpen.value || isModalOpen()) return;
  const tag = (e.target as HTMLElement)?.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA") return;
  if (e.key === "ArrowUp") {
    e.preventDefault();
    goToPrev();
  } else if (e.key === "ArrowDown") {
    e.preventDefault();
    goToNext();
  }
}

onMounted(() => window.addEventListener("keydown", onKeyNav));
onBeforeUnmount(() => window.removeEventListener("keydown", onKeyNav));

////////////////////////////////////////////////////////////////////////
//
async function onSplitSave(splits: Record<string, string>) {
  pickerOpen.value = false;
  await applySplits(splits);
}

function navigateBudget(budgetId: string) {
  router.push({ name: "budget-detail", params: { id: budgetId } });
}

// Open the browser's file picker and upload the chosen file.
//
function onAttach(field: AttachmentField) {
  const input = document.createElement("input");
  input.type = "file";
  input.accept = field === "image" ? "image/*" : "*/*";
  input.onchange = () => {
    const file = input.files?.[0];
    if (file) void uploadAttachment(field, file);
  };
  input.click();
}
</script>

<template>
  <AppShell>
    <template #action>
      <div class="flex items-center gap-1">
        <button
          type="button"
          class="flex h-10 w-10 items-center justify-center rounded-full text-neutral-700 hover:bg-neutral-100"
          aria-label="Back"
          @click="router.back()"
        >
          <IconArrowLeft class="h-5 w-5" />
        </button>
        <button
          v-if="prevTxId"
          type="button"
          class="flex h-10 w-10 items-center justify-center rounded-full text-neutral-700 hover:bg-neutral-100"
          aria-label="Previous transaction"
          @click="goToPrev"
        >
          <IconChevronUp class="h-5 w-5" />
        </button>
        <button
          v-if="nextTxId"
          type="button"
          class="flex h-10 w-10 items-center justify-center rounded-full text-neutral-700 hover:bg-neutral-100"
          aria-label="Next transaction"
          @click="goToNext"
        >
          <IconChevronDown class="h-5 w-5" />
        </button>
      </div>
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
      <TransactionHero
        :party-name="partyName"
        :amount="transaction.amount"
        :formatted-date="formattedDate"
        :pending="transaction.pending"
        :account-name="accountName"
      />

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
            @blur="onDescriptionBlur"
          />
          <p v-if="descriptionError" class="mt-1 text-xs text-coral-600" role="alert">
            {{ descriptionError }}
          </p>
        </div>

        <div v-if="transaction.rawDescription !== transaction.description">
          <label class="text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
            Raw description
          </label>
          <p class="mt-0.5 text-sm text-neutral-600">{{ transaction.rawDescription }}</p>
        </div>

        <div v-if="typeLabel" class="flex items-center gap-2">
          <label
            class="flex-none text-[11px] font-semibold uppercase tracking-wider text-neutral-500"
          >
            Type
          </label>
          <span class="min-w-0 flex-1 border-b border-dotted border-neutral-200" />
          <span class="flex-none text-sm text-neutral-700">{{ typeLabel }}</span>
        </div>

        <div class="flex items-center gap-2">
          <label
            class="flex-none text-[11px] font-semibold uppercase tracking-wider text-neutral-500"
          >
            {{ accountName }} balance after
          </label>
          <span class="min-w-0 flex-1 border-b border-dotted border-neutral-200" />
          <MoneyAmount class="flex-none" :amount="transaction.accountPostedBalance" size="sm" />
        </div>
      </section>

      <!-- Allocations -->
      <AllocationsSection
        :allocations="visibleAllocations"
        :coverage="coverage"
        :pending="transaction.pending"
        :budget-name="budgetName"
        @update="updateAllocation"
        @remove="removeAllocation"
        @assign="pickerOpen = true"
        @navigate-budget="navigateBudget"
      />
      <p v-if="splitError" class="mt-2 text-sm text-coral-600" role="alert">
        {{ splitError }}
      </p>

      <!-- Memo + attachments.  All three are hidden on pending rows
           because the next sync wipes pending transactions and
           reinserts whatever the bank currently shows; anything the
           user attached here would be lost on the next scrape. -->
      <template v-if="!transaction.pending">
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
            @blur="onMemoBlur"
          />
          <p v-if="memoError" class="mt-1 text-xs text-coral-600" role="alert">
            {{ memoError }}
          </p>
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
        <p v-if="attachmentError" class="mt-2 text-sm text-coral-600" role="alert">
          {{ attachmentError }}
        </p>
      </template>

      <!-- Footer -->
      <p class="mt-8 pb-4 text-center text-xs text-neutral-400">
        Transactions are imported from bank statements and cannot be created or deleted.
      </p>
    </template>

    <!-- Split editor dialog -->
    <SplitEditorDialog
      v-if="transaction"
      :open="pickerOpen"
      :budgets="accountBudgets"
      :transaction-amount="transaction.amount"
      :initial-splits="initialSplits"
      :unallocated-budget-id="unallocatedBudgetId"
      @save="onSplitSave"
      @cancel="pickerOpen = false"
    />
  </AppShell>
</template>
