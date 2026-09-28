<script setup lang="ts">
//
// TransactionHero — the top block of the transaction detail view: who,
// how much, when, and on which account.  Presentational.
//

// app imports
//
import MoneyAmount from "@/components/base/MoneyAmount.vue";
import type { Money } from "@/domain/money";
import BaseBadge from "@/components/base/BaseBadge.vue";

////////////////////////////////////////////////////////////////////////
//
defineProps<{
  partyName: string;
  amount: Money;
  formattedDate: string;
  pending: boolean;
  accountName: string;
}>();
</script>

<template>
  <section class="pb-4 pt-2 text-center">
    <h1 class="text-title text-fg">{{ partyName }}</h1>
    <MoneyAmount :amount="amount" size="hero" coloured class="mt-1" />
    <div
      class="mt-1.5 flex items-center justify-center gap-2 text-meta text-fg-muted"
    >
      <span>{{ formattedDate }}</span>
      <BaseBadge v-if="pending" tone="warning" variant="soft">
        PENDING
      </BaseBadge>
      <span v-if="accountName">· {{ accountName }}</span>
    </div>
  </section>
</template>
