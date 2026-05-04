<script setup lang="ts">
//
// BudgetCard — list-row card for a single budget.  (UI_SPEC §4.2)
//
// Layout:
//   [ Name                    ] [ $balance  ]
//   [ meta: type · reset date ] [ of $target ]
//   [====== progress bar ========]
//   [ $X · schedule            ] [ StatusChip ]
//
// When `fillupBudget` is provided, a FillUpBand is appended inside the
// same card container.
//

// 3rd party imports
//
import { IconBucket, IconRepeat, IconTarget } from "@tabler/icons-vue";
import { computed } from "vue";
import { useRouter } from "vue-router";

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
  fillupBudget?: Budget;
}>();

const router = useRouter();

const status = computed(() => budgetStatus(props.budget));
const pct = computed(() => budgetProgress(props.budget));
const tone = computed(() => progressTone(status.value));
const meta = computed(() => budgetMeta(props.budget));

const fundingSchedule = computed(() =>
  props.budget.funding_schedule ? rruleHuman(props.budget.funding_schedule) : null,
);
</script>

<template>
  <article
    class="overflow-hidden rounded-card border border-neutral-200 bg-white"
    @click="router.push(`/budgets/${budget.id}/`)"
  >
    <div class="cursor-pointer px-4 pb-3 pt-4">
      <!-- Row 1: name + balance -->
      <div class="flex items-start justify-between gap-2">
        <div class="flex min-w-0 items-center gap-1.5">
          <IconTarget
            v-if="budget.budget_type === 'G'"
            class="h-4 w-4 flex-none text-neutral-400"
          />
          <IconRepeat
            v-else-if="budget.budget_type === 'R'"
            class="h-4 w-4 flex-none text-neutral-400"
          />
          <IconBucket
            v-else-if="budget.budget_type === 'C'"
            class="h-4 w-4 flex-none text-neutral-400"
          />
          <span class="truncate text-[15px] font-medium text-neutral-900">
            {{ budget.name }}
          </span>
        </div>
        <MoneyAmount
          :amount="budget.balance"
          :currency="budget.balance_currency"
          size="md"
          class="flex-none"
        />
      </div>

      <!-- Row 2: meta + target -->
      <div class="mt-0.5 flex items-center justify-between gap-2">
        <span class="truncate text-[12px] text-secondary">{{ meta }}</span>
        <span v-if="budget.target_balance" class="flex-none text-[12px] text-secondary">
          of&nbsp;<MoneyAmount
            :amount="budget.target_balance"
            :currency="budget.target_balance_currency"
            size="sm"
          />
        </span>
      </div>

      <!-- Progress bar -->
      <ProgressBar class="mt-2.5" :value="pct" :tone="tone" :height="5" />

      <!-- Row 3: funding info + status chip -->
      <div class="mt-2 flex items-center justify-between gap-2">
        <span v-if="budget.next_funding" class="truncate text-[12px] text-secondary">
          <MoneyAmount
            :amount="budget.next_funding.amount"
            :currency="budget.next_funding.amount_currency"
            size="sm"
          />/event<template v-if="fundingSchedule">&thinsp;·&thinsp;{{ fundingSchedule }}</template>
        </span>
        <span
          v-else-if="budget.budget_type === 'C' && budget.funding_amount"
          class="truncate text-[12px] text-secondary"
        >
          <MoneyAmount
            :amount="budget.funding_amount"
            :currency="budget.funding_amount_currency"
            size="sm"
          />/event<template v-if="fundingSchedule">&thinsp;·&thinsp;{{ fundingSchedule }}</template>
        </span>
        <span v-else-if="fundingSchedule" class="truncate text-[12px] text-secondary">
          Funded&thinsp;·&thinsp;{{ fundingSchedule }}
        </span>
        <span v-else class="flex-1" />
        <StatusChip :status="status" class="flex-none" />
      </div>
    </div>

    <!-- Fill-up band (if present) -->
    <FillUpBand v-if="fillupBudget" :budget="fillupBudget" />
  </article>
</template>
