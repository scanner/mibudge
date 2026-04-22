<script setup lang="ts">
//
// BankAccountCreateView — create a new bank account.
// (UI_SPEC §4.9, /app/account/bank-accounts/create/)
//
// Fields: account type grid, name, bank picker, account number,
// currency, posted balance, available balance.
//
// Balances are immutable after creation; a footer note says so.
// The currencies endpoint is a GAP — USD is the only option for now.
//

// 3rd party imports
//
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";

// app imports
//
import AppShell from "@/components/layout/AppShell.vue";
import { createBankAccount } from "@/api/bankAccounts";
import { listBanks } from "@/api/banks";
import { adminEmail } from "@/api/config";
import { useAccountContextStore } from "@/stores/accountContext";
import type { AccountType, Bank } from "@/types/api";

////////////////////////////////////////////////////////////////////////
//
const router = useRouter();
const ctx = useAccountContextStore();

////////////////////////////////////////////////////////////////////////
//
const accountType = ref<AccountType>("C");
const name = ref("");
const selectedBankId = ref<string | null>(null);
const accountNumber = ref("");
const currency = ref("USD");
const postedBalance = ref("");
const availableBalance = ref("");

const banks = ref<Bank[]>([]);
const banksLoading = ref(false);

const saving = ref(false);
const error = ref<string | null>(null);

////////////////////////////////////////////////////////////////////////
//
const ACCOUNT_TYPES: { value: AccountType; label: string; sub: string }[] = [
  { value: "C", label: "Checking", sub: "Day-to-day spending" },
  { value: "S", label: "Savings", sub: "Set aside funds" },
  { value: "X", label: "Credit card", sub: "Track card charges" },
];

////////////////////////////////////////////////////////////////////////
//
onMounted(async () => {
  banksLoading.value = true;
  try {
    const page = await listBanks();
    banks.value = page.results;
  } catch {
    banks.value = [];
  } finally {
    banksLoading.value = false;
  }
});

////////////////////////////////////////////////////////////////////////
//
async function submit() {
  if (!name.value.trim()) {
    error.value = "Account name is required.";
    return;
  }
  if (!selectedBankId.value) {
    error.value = "Please select a bank.";
    return;
  }
  if (!accountNumber.value.trim()) {
    error.value = "Account number is required.";
    return;
  }

  saving.value = true;
  error.value = null;

  const body: Record<string, unknown> = {
    account_type: accountType.value,
    name: name.value.trim(),
    bank: selectedBankId.value,
    currency: currency.value,
    account_number: accountNumber.value.trim(),
  };
  if (postedBalance.value.trim()) body.posted_balance = postedBalance.value.trim();
  if (availableBalance.value.trim()) body.available_balance = availableBalance.value.trim();

  try {
    const created = await createBankAccount(body as Parameters<typeof createBankAccount>[0]);
    await ctx.refresh();
    router.push(`/account/bank-accounts/${created.id}/`);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Failed to create account.";
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <AppShell>
    <div class="mx-auto max-w-lg py-4">
      <h1 class="mb-5 text-[22px] font-medium text-neutral-900">New bank account</h1>

      <div
        v-if="error"
        class="mb-4 rounded-subcard bg-coral-50 px-4 py-3 text-sm text-coral-600"
        role="alert"
      >
        {{ error }}
      </div>

      <form class="space-y-5" @submit.prevent="submit">
        <!-- Account type grid -->
        <div>
          <label class="mb-2 block text-sm font-medium text-neutral-700">Account type</label>
          <div class="grid grid-cols-3 gap-2">
            <button
              v-for="opt in ACCOUNT_TYPES"
              :key="opt.value"
              type="button"
              :class="[
                'rounded-subcard border px-3 py-3 text-left transition-colors',
                accountType === opt.value
                  ? 'border-ocean-400 bg-ocean-50 text-ocean-800'
                  : 'border-neutral-200 bg-white text-neutral-700 hover:bg-neutral-50',
              ]"
              @click="accountType = opt.value"
            >
              <div class="text-sm font-medium">{{ opt.label }}</div>
              <div class="mt-0.5 text-[11px] text-neutral-500">{{ opt.sub }}</div>
            </button>
          </div>
        </div>

        <!-- Name -->
        <div>
          <label class="mb-1.5 block text-sm font-medium text-neutral-700" for="acct-name">
            Account name <span class="text-coral-400">*</span>
          </label>
          <input
            id="acct-name"
            v-model="name"
            type="text"
            required
            class="w-full rounded-subcard border border-neutral-200 px-3 py-2.5 text-sm text-neutral-900 placeholder-neutral-400 focus:border-ocean-400 focus:outline-none focus:ring-1 focus:ring-ocean-400"
            placeholder="e.g. Chase Checking"
          />
        </div>

        <!-- Bank picker -->
        <div>
          <label class="mb-1.5 block text-sm font-medium text-neutral-700" for="acct-bank">
            Bank <span class="text-coral-400">*</span>
          </label>
          <template v-if="banksLoading">
            <div
              class="rounded-subcard border border-neutral-200 px-3 py-2.5 text-sm text-neutral-400"
            >
              Loading banks…
            </div>
          </template>
          <template v-else-if="banks.length === 0">
            <div
              class="rounded-subcard border border-neutral-200 bg-neutral-50 px-3 py-2.5 text-sm text-neutral-500"
            >
              Your bank isn't listed —
              <a v-if="adminEmail" :href="`mailto:${adminEmail}`" class="text-ocean-600 underline"
                >contact support</a
              >
              <span v-else>contact support</span>
              to add it.
            </div>
            <!-- GAP-7: no free-text bank entry yet -->
          </template>
          <template v-else>
            <select
              id="acct-bank"
              v-model="selectedBankId"
              class="w-full rounded-subcard border border-neutral-200 px-3 py-2.5 text-sm text-neutral-900 focus:border-ocean-400 focus:outline-none focus:ring-1 focus:ring-ocean-400"
            >
              <option :value="null" disabled>Select a bank…</option>
              <option v-for="bank in banks" :key="bank.id" :value="bank.id">
                {{ bank.name }}
              </option>
            </select>
          </template>
        </div>

        <!-- Account number (optional) -->
        <div>
          <label class="mb-1.5 block text-sm font-medium text-neutral-700" for="acct-number">
            Account number <span class="text-coral-400">*</span>
          </label>
          <input
            id="acct-number"
            v-model="accountNumber"
            type="text"
            inputmode="numeric"
            class="w-full rounded-subcard border border-neutral-200 px-3 py-2.5 font-mono text-sm text-neutral-900 placeholder-neutral-400 focus:border-ocean-400 focus:outline-none focus:ring-1 focus:ring-ocean-400"
            placeholder="Account number"
          />
        </div>

        <!-- Currency — GAP: hardcoded to USD until /api/v1/currencies/ is live -->
        <div>
          <label class="mb-1.5 block text-sm font-medium text-neutral-700">Currency</label>
          <div
            class="rounded-subcard border border-neutral-200 bg-neutral-50 px-3 py-2.5 text-sm text-neutral-700"
          >
            USD — US Dollar
            <!-- TODO: replace with currency picker once /api/v1/currencies/ endpoint is available -->
          </div>
        </div>

        <!-- Balances -->
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="mb-1.5 block text-sm font-medium text-neutral-700" for="acct-posted">
              Posted balance
              <span class="font-normal text-neutral-400">(optional)</span>
            </label>
            <input
              id="acct-posted"
              v-model="postedBalance"
              type="text"
              inputmode="decimal"
              class="w-full rounded-subcard border border-neutral-200 px-3 py-2.5 font-mono text-sm text-neutral-900 placeholder-neutral-400 focus:border-ocean-400 focus:outline-none focus:ring-1 focus:ring-ocean-400"
              placeholder="0.00"
            />
          </div>
          <div>
            <label class="mb-1.5 block text-sm font-medium text-neutral-700" for="acct-available">
              Available balance
              <span class="font-normal text-neutral-400">(optional)</span>
            </label>
            <input
              id="acct-available"
              v-model="availableBalance"
              type="text"
              inputmode="decimal"
              class="w-full rounded-subcard border border-neutral-200 px-3 py-2.5 font-mono text-sm text-neutral-900 placeholder-neutral-400 focus:border-ocean-400 focus:outline-none focus:ring-1 focus:ring-ocean-400"
              placeholder="0.00"
            />
          </div>
        </div>

        <!-- Actions -->
        <div class="flex gap-3 pt-1">
          <button
            type="submit"
            :disabled="
              saving ||
              !name.trim() ||
              (!selectedBankId && banks.length > 0) ||
              !accountNumber.trim()
            "
            class="flex-1 rounded-subcard bg-ocean-400 py-2.5 text-sm font-medium text-white hover:bg-ocean-600 disabled:opacity-50"
          >
            {{ saving ? "Creating…" : "Create account" }}
          </button>
          <button
            type="button"
            class="flex-1 rounded-subcard border border-neutral-200 py-2.5 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
            @click="router.push('/account/')"
          >
            Cancel
          </button>
        </div>

        <!-- Footer note -->
        <p class="text-center text-xs text-neutral-400">
          Balances are immutable after creation. An Unallocated budget is created automatically.
        </p>
      </form>
    </div>
  </AppShell>
</template>
