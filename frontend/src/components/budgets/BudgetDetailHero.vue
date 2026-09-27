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
import {
  budgetMeta,
  budgetProgress,
  budgetStatus,
  progressTone,
} from "@/domain/budgetStatus";
import { formatInstantDate, formatLocalDate } from "@/domain/dates";
import { BUDGET_TYPE_LABELS } from "@/domain/labels";
import { rruleHuman } from "@/domain/rrule";
import type { Budget } from "@/models/budget";

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

const typeLabel = computed(() => BUDGET_TYPE_LABELS[props.budget.budgetType]);

const nextFunding = computed(() => {
  if (!props.budget.fundingSchedule) return null;
  return rruleHuman(props.budget.fundingSchedule);
});

const SHORT_DATE: Intl.DateTimeFormatOptions = {
  month: "short",
  day: "numeric",
  year: "numeric",
};

const startDate = computed(() =>
  formatInstantDate(props.budget.createdAt, SHORT_DATE),
);

// `targetDate` is a calendar date; `formatLocalDate` renders that day
// in every browser zone.
//
const endDate = computed(() =>
  props.budget.targetDate
    ? formatLocalDate(props.budget.targetDate, SHORT_DATE)
    : null,
);
</script>

<template>
  <div class="overflow-hidden rounded-card border border-border bg-surface">
    <div class="px-5 pb-4 pt-5">
      <!-- Row 1: name + type chip -->
      <div class="flex items-center justify-between gap-3">
        <h1 class="truncate text-page-title text-fg">
          {{ budget.name }}
        </h1>
        <StatusChip :status="status" :label="typeLabel" class="flex-none" />
      </div>

      <!-- Row 2: account + meta -->
      <p class="mt-1 text-body-sm text-fg-muted">
        <span v-if="accountName">{{ accountName }}&thinsp;·&thinsp;</span>
        {{ meta }}
      </p>

      <!-- Row 3: balance / target -->
      <div class="mt-3 flex items-baseline gap-2">
        <MoneyAmount :amount="budget.balance" size="hero" :coloured="true" />
        <span
          v-if="budget.targetBalance"
          class="text-amount font-normal text-fg-subtle"
        >
          /&nbsp;<MoneyAmount :amount="budget.targetBalance" size="md" />
        </span>
      </div>

      <!-- Progress bar -->
      <ProgressBar class="mt-3" :value="pct" :tone="tone" :height="8" />

      <!-- Axis labels -->
      <div
        v-if="endDate"
        class="mt-1 flex justify-between text-meta text-fg-subtle"
      >
        <span>{{ startDate }}</span>
        <span>{{ endDate }}</span>
      </div>

      <!-- Status + next funding -->
      <div class="mt-2 flex items-center justify-between gap-2">
        <StatusChip :status="status" />
        <span v-if="nextFunding" class="text-meta text-fg-muted">
          Next funding: {{ nextFunding }}
        </span>
      </div>
    </div>

    <!-- Fill-up band -->
    <FillUpBand v-if="fillupBudget" :budget="fillupBudget" />
  </div>
</template>
