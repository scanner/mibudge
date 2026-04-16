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
import { budgetProgress, progressTone, budgetStatus } from "@/utils/budget";
import { rruleHuman } from "@/utils/rrule";
import type { Budget } from "@/types/api";
import { IconArrowBarToDown } from "@tabler/icons-vue";

////////////////////////////////////////////////////////////////////////
//
const props = defineProps<{ budget: Budget }>();

const pct = computed(() => budgetProgress(props.budget));
const tone = computed(() => progressTone(budgetStatus(props.budget)));
const schedule = computed(() =>
  props.budget.funding_schedule ? rruleHuman(props.budget.funding_schedule) : null,
);
</script>

<template>
  <div class="border-t border-[#D4E9F7] bg-[#F5FAFF] px-4 pb-3 pt-2">
    <div class="flex items-center justify-between">
      <div class="flex items-center gap-1.5 text-[13px] text-ocean-600">
        <IconArrowBarToDown class="h-3.5 w-3.5 flex-none" />
        <span>Next cycle saving</span>
      </div>
      <div class="text-right">
        <span class="font-mono text-[13px] font-medium text-ocean-800">
          <MoneyAmount :amount="budget.balance" :currency="budget.balance_currency" size="sm" />
        </span>
        <span v-if="budget.target_balance" class="font-mono text-[11px] text-neutral-400">
          &nbsp;of&nbsp;
          <MoneyAmount
            :amount="budget.target_balance"
            :currency="budget.target_balance_currency"
            size="sm"
          />
        </span>
      </div>
    </div>

    <ProgressBar class="mt-1.5" :value="pct" :tone="tone" :height="3" />

    <p v-if="schedule" class="mt-1.5 text-[11px] text-neutral-500">
      {{ schedule }} · ready at cycle reset
    </p>
  </div>
</template>
