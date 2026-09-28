<script setup lang="ts">
//
// BudgetCard — list-row card for a single budget.
//
// Layout:
//   [ Name                    ] [ $balance  ]
//   [ meta: type · reset date ] [ of $target ]
//   [====== progress bar ========]
//   [ $X · schedule            ] [ StatusChip ]
//
// When `fillupBudget` is provided, a FillUpBand is appended inside the
// same card container.  Clicking the card emits `select` with the
// budget id; the parent navigates.
//

// 3rd party imports
//
import { IconBucket, IconRepeat, IconTarget } from "@tabler/icons-vue";
import { computed } from "vue";

// app imports
//
import FillUpBand from "./FillUpBand.vue";
import MoneyAmount from "@/components/base/MoneyAmount.vue";
import ProgressBar from "@/components/base/ProgressBar.vue";
import StatusChip from "@/components/base/StatusChip.vue";
import {
  budgetMeta,
  budgetProgress,
  budgetStatus,
  progressTone,
} from "@/domain/budgetStatus";
import { rruleHuman } from "@/domain/rrule";
import type { Budget } from "@/models/budget";
import BaseCard from "@/components/base/BaseCard.vue";

////////////////////////////////////////////////////////////////////////
//
const props = defineProps<{
  budget: Budget;
  fillupBudget?: Budget;
}>();

const emit = defineEmits<{ (e: "select", budgetId: string): void }>();

const status = computed(() => budgetStatus(props.budget));
const pct = computed(() => budgetProgress(props.budget));
const tone = computed(() => progressTone(status.value));
const meta = computed(() => budgetMeta(props.budget));

const fundingSchedule = computed(() =>
  props.budget.fundingSchedule
    ? rruleHuman(props.budget.fundingSchedule)
    : null,
);
</script>

<template>
  <BaseCard as="article" @click="emit('select', budget.id)">
    <div class="cursor-pointer px-4 pb-3 pt-4">
      <!-- Row 1: name + balance -->
      <div class="flex items-start justify-between gap-2">
        <div class="flex min-w-0 items-center gap-1.5">
          <IconTarget
            v-if="budget.budgetType === 'G'"
            class="size-icon-sm flex-none text-icon-muted"
          />
          <IconRepeat
            v-else-if="budget.budgetType === 'R'"
            class="size-icon-sm flex-none text-icon-muted"
          />
          <IconBucket
            v-else-if="budget.budgetType === 'C'"
            class="size-icon-sm flex-none text-icon-muted"
          />
          <span class="truncate text-item-title text-fg">
            {{ budget.name }}
          </span>
        </div>
        <MoneyAmount :amount="budget.balance" size="md" class="flex-none" />
      </div>

      <!-- Row 2: meta + target -->
      <div class="mt-0.5 flex items-center justify-between gap-2">
        <span class="truncate text-meta text-fg-muted">{{ meta }}</span>
        <span
          v-if="budget.targetBalance"
          class="flex-none text-meta text-fg-muted"
        >
          of&nbsp;<MoneyAmount :amount="budget.targetBalance" size="sm" />
        </span>
      </div>

      <!-- Progress bar -->
      <ProgressBar class="mt-2.5" :value="pct" :tone="tone" size="md" />

      <!-- Row 3: funding info + status chip -->
      <div class="mt-2 flex items-center justify-between gap-2">
        <span
          v-if="budget.nextFunding"
          class="truncate text-meta text-fg-muted"
        >
          <MoneyAmount
            :amount="budget.nextFunding.amount"
            size="sm"
          />/event<template v-if="fundingSchedule"
            >&thinsp;·&thinsp;{{ fundingSchedule }}</template
          >
        </span>
        <span
          v-else-if="budget.budgetType === 'C' && budget.fundingAmount"
          class="truncate text-meta text-fg-muted"
        >
          <MoneyAmount
            :amount="budget.fundingAmount"
            size="sm"
          />/event<template v-if="fundingSchedule"
            >&thinsp;·&thinsp;{{ fundingSchedule }}</template
          >
        </span>
        <span
          v-else-if="fundingSchedule"
          class="truncate text-meta text-fg-muted"
        >
          Funded&thinsp;·&thinsp;{{ fundingSchedule }}
        </span>
        <span v-else class="flex-1" />
        <StatusChip :status="status" class="flex-none" />
      </div>
    </div>

    <!-- Fill-up band (if present) -->
    <FillUpBand v-if="fillupBudget" :budget="fillupBudget" />
  </BaseCard>
</template>
