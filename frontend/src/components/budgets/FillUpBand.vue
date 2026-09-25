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
import MoneyAmount from "@/components/shared/MoneyAmount.vue";
import ProgressBar from "@/components/shared/ProgressBar.vue";
import { budgetProgress, budgetStatus, progressTone } from "@/domain/budgetStatus";
import type { Budget } from "@/models/budget";

////////////////////////////////////////////////////////////////////////
//
const props = defineProps<{ budget: Budget }>();

const pct = computed(() => budgetProgress(props.budget));
const tone = computed(() => progressTone(budgetStatus(props.budget)));
</script>

<template>
  <div class="border-t border-[#D4E9F7] bg-[#F5FAFF] px-4 pb-3 pt-2 group-hover:bg-[#E8F4FD]">
    <div class="flex items-center justify-between gap-2">
      <span v-if="budget.nextFunding" class="truncate text-[12px] text-ocean-600">
        <MoneyAmount :amount="budget.nextFunding.amount" size="sm" />/event
      </span>
      <span v-else class="flex-1" />
      <div class="flex-none text-right">
        <span class="font-mono text-[13px] font-medium text-ocean-800">
          <MoneyAmount :amount="budget.balance" size="sm" />
        </span>
        <span v-if="budget.targetBalance" class="font-mono text-[11px] text-neutral-400">
          &nbsp;of&nbsp;
          <MoneyAmount :amount="budget.targetBalance" size="sm" />
        </span>
      </div>
    </div>
    <ProgressBar class="mt-1.5" :value="pct" :tone="tone" :height="3" />
  </div>
</template>
