<script setup lang="ts">
//
// TransactionHero — the top block of the transaction detail view: who,
// how much, when, and on which account.  Presentational.
//

// app imports
//
import MoneyAmount from "@/components/shared/MoneyAmount.vue";
import type { Money } from "@/domain/money";

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
    <h1 class="text-lg font-medium text-neutral-900">{{ partyName }}</h1>
    <MoneyAmount :amount="amount" size="hero" coloured class="mt-1" />
    <div
      class="mt-1.5 flex items-center justify-center gap-2 text-xs text-neutral-500"
    >
      <span>{{ formattedDate }}</span>
      <span
        v-if="pending"
        class="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-600"
      >
        PENDING
      </span>
      <span v-if="accountName">· {{ accountName }}</span>
    </div>
  </section>
</template>
