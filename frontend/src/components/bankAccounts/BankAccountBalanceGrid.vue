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
    <div class="rounded-card border border-border bg-surface px-4 py-3">
      <div class="mb-0.5 text-overline uppercase text-fg-muted">
        Posted balance
      </div>
      <MoneyAmount :amount="account.postedBalance" size="md" />
    </div>
    <div class="rounded-card border border-border bg-surface px-4 py-3">
      <div class="mb-0.5 text-overline uppercase text-fg-muted">
        Available balance
      </div>
      <MoneyAmount :amount="account.availableBalance" size="md" />
    </div>
    <div class="rounded-card border border-border bg-surface px-4 py-3">
      <div class="mb-0.5 text-overline uppercase text-fg-muted">
        Unallocated
      </div>
      <MoneyAmount
        v-if="unallocated"
        :amount="unallocated"
        size="md"
        :coloured="false"
      />
      <span v-else class="font-mono text-amount text-fg-muted">—</span>
    </div>
    <div class="rounded-card border border-border bg-surface px-4 py-3">
      <div class="mb-0.5 text-overline uppercase text-fg-muted">Currency</div>
      <span class="font-mono text-amount text-fg">
        {{ account.currency }}
      </span>
    </div>
  </section>
</template>
