<script setup lang="ts">
//
// FillUpBand — attached to the bottom of a recurring BudgetCard or the
// detail hero when with_fillup_goal=true.  Shows the associated fill-up
// budget's progress.  (UI_SPEC §4.2)
//
// Blue-tinted background, 3px progress bar.
//

// 3rd party imports
//
import { computed } from "vue";

// app imports
//
import MoneyAmount from "@/components/base/MoneyAmount.vue";
import ProgressBar from "@/components/base/ProgressBar.vue";
import {
  budgetProgress,
  budgetStatus,
  progressTone,
} from "@/domain/budgetStatus";
import type { Budget } from "@/models/budget";

////////////////////////////////////////////////////////////////////////
//
const props = defineProps<{ budget: Budget }>();

const pct = computed(() => budgetProgress(props.budget));
const tone = computed(() => progressTone(budgetStatus(props.budget)));
</script>

<template>
  <div
    class="border-t border-info-border/60 bg-info-bg/50 px-4 pb-3 pt-2 group-hover:bg-info-bg"
  >
    <div class="flex items-center justify-between gap-2">
      <span v-if="budget.nextFunding" class="truncate text-meta text-info-fg">
        <MoneyAmount :amount="budget.nextFunding.amount" size="sm" />/event
      </span>
      <span v-else class="flex-1" />
      <div class="flex-none text-right">
        <span class="font-mono text-amount-sm font-medium text-info-fg">
          <MoneyAmount :amount="budget.balance" size="sm" />
        </span>
        <span
          v-if="budget.targetBalance"
          class="font-mono text-amount-sm text-fg-subtle"
        >
          &nbsp;of&nbsp;
          <MoneyAmount :amount="budget.targetBalance" size="sm" />
        </span>
      </div>
    </div>
    <ProgressBar class="mt-1.5" :value="pct" :tone="tone" size="sm" />
  </div>
</template>
