<script setup lang="ts">
//
// BankAccountDetailView — read-only hero grid, details, owners, budget
// count, inline name edit, and delete with confirmation.
// (UI_SPEC §4.8, /app/account/bank-accounts/:id/)
//

// 3rd party imports
//
import { IconChevronRight, IconPencil } from "@tabler/icons-vue";
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

// app imports
//
import ConfirmSheet from "@/components/shared/ConfirmSheet.vue";
import MoneyAmount from "@/components/shared/MoneyAmount.vue";
import AppShell from "@/components/layout/AppShell.vue";
import { deleteBankAccount, getBankAccount, updateBankAccount } from "@/api/bankAccounts";
import { getBank } from "@/api/banks";
import { listBudgets } from "@/api/budgets";
import { useAccountContextStore } from "@/stores/accountContext";
import { useBudgetsStore } from "@/stores/budgets";
import type { BankAccount } from "@/types/api";

////////////////////////////////////////////////////////////////////////
//
const props = defineProps<{ id: string }>();

const router = useRouter();
const ctx = useAccountContextStore();
const budgetsStore = useBudgetsStore();

const account = ref<BankAccount | null>(null);
const bankName = ref<string | null>(null);
const budgetCount = ref<number | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);

// Inline edit state (name + account number).
const editing = ref(false);
const editName = ref("");
const editAccountNumber = ref("");
const saving = ref(false);
const nameError = ref<string | null>(null);

// Delete confirmation.
const confirmDelete = ref(false);
const deleting = ref(false);

////////////////////////////////////////////////////////////////////////
//
const ACCOUNT_TYPE_LABELS: Record<string, string> = {
  C: "Checking",
  S: "Savings",
  X: "Credit card",
};

const unallocated = computed(() => {
  if (!account.value?.unallocated_budget) return null;
  return budgetsStore.byId(account.value.unallocated_budget);
});

const createdDate = computed(() => {
  if (!account.value) return "";
  return new Date(account.value.created_at).toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
});

////////////////////////////////////////////////////////////////////////
//
onMounted(async () => {
  loading.value = true;
  error.value = null;
  try {
    const [acct, budgetsPage] = await Promise.all([
      getBankAccount(props.id),
      listBudgets({ bank_account: props.id }),
    ]);
    account.value = acct;
    editName.value = acct.name;

    // Count user-facing budgets (exclude unallocated and auto-created fill-up goals).
    budgetCount.value = budgetsPage.results.filter(
      (b) => b.id !== acct.unallocated_budget && b.budget_type !== "A",
    ).length;

    // Load unallocated balance.
    if (acct.unallocated_budget && !budgetsStore.byId(acct.unallocated_budget)) {
      budgetsStore.fetchOne(acct.unallocated_budget);
    }

    // Resolve bank name.
    if (acct.bank) {
      try {
        const bank = await getBank(acct.bank);
        bankName.value = bank.name;
      } catch {
        bankName.value = null;
      }
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Failed to load account.";
  } finally {
    loading.value = false;
  }
});

////////////////////////////////////////////////////////////////////////
//
function startEdit() {
  if (!account.value) return;
  editName.value = account.value.name;
  editAccountNumber.value = account.value.account_number ?? "";
  editing.value = true;
  nameError.value = null;
}

function cancelEdit() {
  editing.value = false;
  nameError.value = null;
}

async function saveName() {
  if (!account.value || !editName.value.trim()) {
    nameError.value = "Name is required.";
    return;
  }
  saving.value = true;
  nameError.value = null;
  try {
    const body: Partial<typeof account.value> = { name: editName.value.trim() };
    if (editAccountNumber.value.trim() !== (account.value.account_number ?? "")) {
      body.account_number = editAccountNumber.value.trim() || null;
    }
    const updated = await updateBankAccount(props.id, body);
    account.value = updated;
    editing.value = false;
    await ctx.refresh();
  } catch (err) {
    nameError.value = err instanceof Error ? err.message : "Failed to save.";
  } finally {
    saving.value = false;
  }
}

////////////////////////////////////////////////////////////////////////
//
async function deleteAccount() {
  deleting.value = true;
  try {
    await deleteBankAccount(props.id);
    await ctx.refresh();
    // If we deleted the active account, switch to first remaining.
    if (ctx.activeBankAccountId === props.id) {
      ctx.setActive(ctx.accounts[0]?.id ?? null);
    }
    router.push("/account/");
  } catch {
    deleting.value = false;
    confirmDelete.value = false;
  }
}
</script>

<template>
  <AppShell>
    <div v-if="loading" class="mt-8 flex justify-center">
      <span class="text-sm text-secondary">Loading…</span>
    </div>

    <div
      v-else-if="error"
      class="mt-4 rounded-subcard bg-coral-50 px-4 py-3 text-sm text-coral-600"
      role="alert"
    >
      {{ error }}
    </div>

    <div v-else-if="account" class="mx-auto max-w-lg space-y-5 py-4">
      <!-- Inline name editor -->
      <div v-if="editing" class="rounded-card border border-ocean-400 bg-white px-4 py-4">
        <label class="mb-1.5 block text-sm font-medium text-neutral-700" for="edit-name">
          Account name
        </label>
        <input
          id="edit-name"
          v-model="editName"
          type="text"
          class="w-full rounded-subcard border border-neutral-200 px-3 py-2.5 text-sm text-neutral-900 focus:border-ocean-400 focus:outline-none focus:ring-1 focus:ring-ocean-400"
          @keydown.enter="saveName"
          @keydown.escape="cancelEdit"
        />
        <label
          class="mb-1.5 mt-3 block text-sm font-medium text-neutral-700"
          for="edit-account-number"
        >
          Account number
        </label>
        <input
          id="edit-account-number"
          v-model="editAccountNumber"
          type="text"
          inputmode="numeric"
          class="w-full rounded-subcard border border-neutral-200 px-3 py-2.5 font-mono text-sm text-neutral-900 focus:border-ocean-400 focus:outline-none focus:ring-1 focus:ring-ocean-400"
          @keydown.enter="saveName"
          @keydown.escape="cancelEdit"
        />
        <p v-if="nameError" class="mt-1 text-xs text-coral-600">{{ nameError }}</p>
        <div class="mt-3 flex gap-2">
          <button
            type="button"
            :disabled="saving"
            class="flex-1 rounded-subcard bg-ocean-400 py-2 text-sm font-medium text-white hover:bg-ocean-600 disabled:opacity-50"
            @click="saveName"
          >
            {{ saving ? "Saving…" : "Save" }}
          </button>
          <button
            type="button"
            class="flex-1 rounded-subcard border border-neutral-200 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
            @click="cancelEdit"
          >
            Cancel
          </button>
        </div>
      </div>

      <!-- Account name heading (non-editing) -->
      <div v-else>
        <div class="flex items-center gap-2">
          <h1 class="text-[22px] font-medium text-neutral-900">{{ account.name }}</h1>
          <button
            type="button"
            class="flex h-7 w-7 flex-none items-center justify-center rounded-full text-neutral-400 hover:bg-neutral-100 hover:text-neutral-600"
            aria-label="Edit account"
            @click="startEdit"
          >
            <IconPencil class="h-4 w-4" />
          </button>
        </div>
        <p class="text-sm text-secondary">
          {{ ACCOUNT_TYPE_LABELS[account.account_type] ?? account.account_type }}
          <template v-if="bankName"> · {{ bankName }}</template>
        </p>
      </div>

      <!-- Hero balance grid (2×2) -->
      <section class="grid grid-cols-2 gap-3">
        <div class="rounded-card border border-neutral-200 bg-white px-4 py-3">
          <div class="mb-0.5 text-[11px] font-semibold uppercase tracking-wider text-secondary">
            Posted balance
          </div>
          <MoneyAmount
            :amount="account.posted_balance"
            :currency="account.posted_balance_currency"
            size="md"
          />
        </div>
        <div class="rounded-card border border-neutral-200 bg-white px-4 py-3">
          <div class="mb-0.5 text-[11px] font-semibold uppercase tracking-wider text-secondary">
            Available balance
          </div>
          <MoneyAmount
            :amount="account.available_balance"
            :currency="account.available_balance_currency"
            size="md"
          />
        </div>
        <div class="rounded-card border border-neutral-200 bg-white px-4 py-3">
          <div class="mb-0.5 text-[11px] font-semibold uppercase tracking-wider text-secondary">
            Unallocated
          </div>
          <MoneyAmount
            v-if="unallocated"
            :amount="unallocated.balance"
            :currency="unallocated.balance_currency"
            size="md"
            :coloured="false"
          />
          <span v-else class="font-mono text-[15px] font-medium text-secondary">—</span>
        </div>
        <div class="rounded-card border border-neutral-200 bg-white px-4 py-3">
          <div class="mb-0.5 text-[11px] font-semibold uppercase tracking-wider text-secondary">
            Currency
          </div>
          <span class="font-mono text-[15px] font-medium text-neutral-900">
            {{ account.currency }}
          </span>
        </div>
      </section>

      <!-- Details -->
      <section class="overflow-hidden rounded-card border border-neutral-200 bg-white">
        <h2
          class="border-b border-neutral-100 px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-secondary"
        >
          Details
        </h2>
        <dl class="divide-y divide-neutral-100">
          <div class="flex items-center justify-between px-4 py-3">
            <dt class="text-sm text-secondary">Account number</dt>
            <dd class="flex items-center gap-2">
              <span class="font-mono text-sm text-neutral-900">
                {{ account.account_number ? `····${account.account_number.slice(-4)}` : "—" }}
              </span>
              <button
                type="button"
                class="flex h-6 w-6 flex-none items-center justify-center rounded-full text-neutral-400 hover:bg-neutral-100 hover:text-neutral-600"
                aria-label="Edit account number"
                @click="startEdit"
              >
                <IconPencil class="h-3.5 w-3.5" />
              </button>
            </dd>
          </div>
          <div class="flex items-center justify-between px-4 py-3">
            <dt class="text-sm text-secondary">Bank</dt>
            <dd class="text-sm text-neutral-900">{{ bankName ?? "—" }}</dd>
          </div>
          <div class="flex items-center justify-between px-4 py-3">
            <dt class="text-sm text-secondary">Created</dt>
            <dd class="text-sm text-neutral-900">{{ createdDate }}</dd>
          </div>
        </dl>
      </section>

      <!-- Owners -->
      <section class="overflow-hidden rounded-card border border-neutral-200 bg-white">
        <h2
          class="border-b border-neutral-100 px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-secondary"
        >
          Owners
        </h2>
        <ul class="divide-y divide-neutral-100">
          <li
            v-for="owner in account.owners"
            :key="owner"
            class="px-4 py-3 text-sm text-neutral-900"
          >
            {{ owner }}
          </li>
          <li v-if="!account.owners?.length" class="px-4 py-3 text-sm text-neutral-400">—</li>
        </ul>
      </section>

      <!-- Budgets -->
      <section class="overflow-hidden rounded-card border border-neutral-200 bg-white">
        <button
          type="button"
          class="flex w-full items-center justify-between px-4 py-3.5 text-left hover:bg-neutral-50"
          @click="
            ctx.setActive(props.id);
            router.push('/budgets/');
          "
        >
          <div>
            <div class="text-sm font-medium text-neutral-900">
              Budgets
              <span v-if="budgetCount !== null" class="ml-1.5 text-secondary">
                {{ budgetCount }}
              </span>
            </div>
            <div class="text-xs text-secondary">View all budgets for this account</div>
          </div>
          <IconChevronRight class="h-4 w-4 flex-none text-neutral-400" />
        </button>
      </section>

      <!-- Delete -->
      <section class="pt-2">
        <button
          type="button"
          class="w-full rounded-card border border-coral-400 py-3 text-sm font-medium text-coral-600 hover:bg-coral-50"
          @click="confirmDelete = true"
        >
          Delete account
        </button>
        <p class="mt-2 px-1 text-center text-xs text-neutral-400">
          Deletes all budgets, transactions, and allocations for this account.
        </p>
      </section>
    </div>

    <!-- Delete confirmation sheet -->
    <ConfirmSheet
      :open="confirmDelete"
      title="Delete account?"
      :message="`This will permanently delete &quot;${account?.name}&quot; and all its budgets, transactions, and allocations. This cannot be undone.`"
      confirm-label="Delete account"
      @confirm="deleteAccount"
      @cancel="confirmDelete = false"
    />
  </AppShell>
</template>
