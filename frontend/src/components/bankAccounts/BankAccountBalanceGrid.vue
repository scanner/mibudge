<script setup lang="ts">
//
// BankAccountBalanceGrid — the 2×2 balance tiles on the bank-account
// page: posted, available, Unallocated and currency.  Presentational.
//

// app imports
//
import MoneyAmount from "@/components/shared/MoneyAmount.vue";
import type { Money } from "@/domain/money";
import type { BankAccount } from "@/models/bankAccount";

////////////////////////////////////////////////////////////////////////
//
defineProps<{
  account: BankAccount;
  // `null` until the Unallocated budget is loaded.
  unallocated: Money | null;
}>();
</script>

<template>
  <!-- Hero balance grid (2×2) -->
  <section class="grid grid-cols-2 gap-3">
    <div class="rounded-card border border-neutral-200 bg-white px-4 py-3">
      <div
        class="mb-0.5 text-[11px] font-semibold uppercase tracking-wider text-secondary"
      >
        Posted balance
      </div>
      <MoneyAmount :amount="account.postedBalance" size="md" />
    </div>
    <div class="rounded-card border border-neutral-200 bg-white px-4 py-3">
      <div
        class="mb-0.5 text-[11px] font-semibold uppercase tracking-wider text-secondary"
      >
        Available balance
      </div>
      <MoneyAmount :amount="account.availableBalance" size="md" />
    </div>
    <div class="rounded-card border border-neutral-200 bg-white px-4 py-3">
      <div
        class="mb-0.5 text-[11px] font-semibold uppercase tracking-wider text-secondary"
      >
        Unallocated
      </div>
      <MoneyAmount
        v-if="unallocated"
        :amount="unallocated"
        size="md"
        :coloured="false"
      />
      <span v-else class="font-mono text-[15px] font-medium text-secondary"
        >—</span
      >
    </div>
    <div class="rounded-card border border-neutral-200 bg-white px-4 py-3">
      <div
        class="mb-0.5 text-[11px] font-semibold uppercase tracking-wider text-secondary"
      >
        Currency
      </div>
      <span class="font-mono text-[15px] font-medium text-neutral-900">
        {{ account.currency }}
      </span>
    </div>
  </section>
</template>
