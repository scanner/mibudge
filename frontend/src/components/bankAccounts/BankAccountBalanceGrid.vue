<script setup lang="ts">
//
// BankAccountBalanceGrid — the 2×2 balance tiles on the bank-account
// page: posted, available, Unallocated and currency.  Presentational.
//

// app imports
//
import MoneyAmount from "@/components/base/MoneyAmount.vue";
import type { Money } from "@/domain/money";
import type { BankAccount } from "@/models/bankAccount";
import BaseSectionHeader from "@/components/base/BaseSectionHeader.vue";
import BaseCard from "@/components/base/BaseCard.vue";

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
    <BaseCard padded>
      <BaseSectionHeader title="Posted balance" as="div" class="mb-0.5" />
      <MoneyAmount :amount="account.postedBalance" size="md" />
    </BaseCard>
    <BaseCard padded>
      <BaseSectionHeader title="Available balance" as="div" class="mb-0.5" />
      <MoneyAmount :amount="account.availableBalance" size="md" />
    </BaseCard>
    <BaseCard padded>
      <BaseSectionHeader title="Unallocated" as="div" class="mb-0.5" />
      <MoneyAmount
        v-if="unallocated"
        :amount="unallocated"
        size="md"
        :coloured="false"
      />
      <span v-else class="font-mono text-amount text-fg-muted">—</span>
    </BaseCard>
    <BaseCard padded>
      <BaseSectionHeader title="Currency" as="div" class="mb-0.5" />
      <span class="font-mono text-amount text-fg">
        {{ account.currency }}
      </span>
    </BaseCard>
  </section>
</template>
