<script setup lang="ts">
//
// BudgetDetailHero — the top "hero" block on BudgetDetailView.
// (UI_SPEC §4.3)
//
// [ Budget name        ] [ type chip ]
// [ account · date/cycle meta        ]
// [ $balance              / $target  ]
// [======= progress bar (8px) =======]
// [ date start            date end   ]
// [ StatusChip      Next funding: X  ]
//
// A FillUpBand is appended inside the card when with_fillup_goal=true
// and fillupBudget is provided.
//

// 3rd party imports
//
import { computed } from "vue";

// app imports
//
import FillUpBand from "./FillUpBand.vue";
import MoneyAmount from "@/components/shared/MoneyAmount.vue";
import ProgressBar from "@/components/shared/ProgressBar.vue";
import StatusChip from "@/components/shared/StatusChip.vue";
import { budgetMeta, budgetProgress, budgetStatus, progressTone } from "@/utils/budget";
import { rruleHuman } from "@/utils/rrule";
import type { Budget } from "@/types/api";

////////////////////////////////////////////////////////////////////////
//
const props = defineProps<{
  budget: Budget;
  accountName?: string;
  fillupBudget?: Budget;
}>();

const status = computed(() => budgetStatus(props.budget));
const pct = computed(() => budgetProgress(props.budget));
const tone = computed(() => progressTone(status.value));
const meta = computed(() => budgetMeta(props.budget));

const typeLabel = computed(() => {
  switch (props.budget.budget_type) {
    case "G":
      return "Goal";
    case "R":
      return "Recurring";
    case "A":
      return "Fill-up";
    case "C":
      return "Capped";
  }
});

const nextFunding = computed(() => {
  if (!props.budget.funding_schedule) return null;
  return rruleHuman(props.budget.funding_schedule);
});

const startDate = computed(() => {
  const d = new Date(props.budget.created_at);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
});

const endDate = computed(() => {
  if (!props.budget.target_date) return null;
  const d = new Date(props.budget.target_date);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
});
</script>

<template>
  <div class="overflow-hidden rounded-card border border-neutral-200 bg-white">
    <div class="px-5 pb-4 pt-5">
      <!-- Row 1: name + type chip -->
      <div class="flex items-center justify-between gap-3">
        <h1 class="truncate text-[22px] font-medium text-neutral-900">
          {{ budget.name }}
        </h1>
        <StatusChip :status="status" :label="typeLabel" class="flex-none" />
      </div>

      <!-- Row 2: account + meta -->
      <p class="mt-1 text-sm text-neutral-500">
        <span v-if="accountName">{{ accountName }}&thinsp;·&thinsp;</span>
        {{ meta }}
      </p>

      <!-- Row 3: balance / target -->
      <div class="mt-3 flex items-baseline gap-2">
        <MoneyAmount
          :amount="budget.balance"
          :currency="budget.balance_currency"
          size="hero"
          :coloured="true"
        />
        <span v-if="budget.target_balance" class="text-[15px] text-neutral-400">
          /&nbsp;<MoneyAmount
            :amount="budget.target_balance"
            :currency="budget.target_balance_currency"
            size="md"
          />
        </span>
      </div>

      <!-- Progress bar -->
      <ProgressBar class="mt-3" :value="pct" :tone="tone" :height="8" />

      <!-- Axis labels -->
      <div v-if="endDate" class="mt-1 flex justify-between text-[11px] text-neutral-400">
        <span>{{ startDate }}</span>
        <span>{{ endDate }}</span>
      </div>

      <!-- Status + next funding -->
      <div class="mt-2 flex items-center justify-between gap-2">
        <StatusChip :status="status" />
        <span v-if="nextFunding" class="text-[12px] text-neutral-500">
          Next funding: {{ nextFunding }}
        </span>
      </div>
    </div>

    <!-- Fill-up band -->
    <FillUpBand v-if="fillupBudget" :budget="fillupBudget" />
  </div>
</template>
