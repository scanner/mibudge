<script setup lang="ts">
//
// BudgetConfigSection — the read-only "Configuration" card on the
// budget detail view: the type-specific settings and the next funding
// deposit.  Presentational; editing happens in the edit sheet.
//
// For a recurring budget with a fill-up goal the next deposit belongs
// to the fill-up child, so it is read from `fillupBudget`.
//

// 3rd party imports
//
import {
  IconCalendar,
  IconClock,
  IconCoin,
  IconRefresh,
  IconTarget,
} from "@tabler/icons-vue";
import { computed } from "vue";

// app imports
//
import MoneyAmount from "@/components/shared/MoneyAmount.vue";
import type { LocalDate } from "@/domain/dates";
import { daysBetween, formatLocalDate } from "@/domain/dates";
import { rruleHuman } from "@/domain/rrule";
import type { Budget } from "@/models/budget";

////////////////////////////////////////////////////////////////////////
//
const props = defineProps<{
  budget: Budget;
  fillupBudget: Budget | null;
  // Today in the profile timezone.
  today: LocalDate;
}>();

const SHORT_DATE: Intl.DateTimeFormatOptions = {
  month: "short",
  day: "numeric",
  year: "numeric",
};

function shortDate(date: LocalDate | null): string {
  return date ? formatLocalDate(date, SHORT_DATE) : "—";
}

function schedule(rule: string | null): string {
  return rule ? rruleHuman(rule) : "—";
}

////////////////////////////////////////////////////////////////////////
//
const nextFunding = computed(() => {
  const b = props.budget;
  const nf =
    b.budgetType === "R" && b.fillupGoalId
      ? (props.fillupBudget?.nextFunding ?? null)
      : b.nextFunding;
  if (!nf) return null;
  return { ...nf, daysAway: daysBetween(props.today, nf.date) };
});
</script>

<template>
  <section
    class="overflow-hidden rounded-card border border-neutral-200 bg-white"
  >
    <h2
      class="border-b border-neutral-100 px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-neutral-500"
    >
      Configuration
    </h2>

    <!-- Goal-specific rows -->
    <template v-if="budget.budgetType === 'G'">
      <div
        class="flex items-center gap-3 border-b border-neutral-100 px-4 py-3"
      >
        <IconTarget class="h-4 w-4 flex-none text-neutral-400" />
        <span class="flex-1 text-sm text-neutral-700">Target amount</span>
        <MoneyAmount
          v-if="budget.targetBalance"
          :amount="budget.targetBalance"
          size="md"
        />
        <span v-else class="text-sm text-secondary">—</span>
      </div>
      <div
        class="flex items-center gap-3 border-b border-neutral-100 px-4 py-3"
      >
        <IconCalendar class="h-4 w-4 flex-none text-neutral-400" />
        <span class="flex-1 text-sm text-neutral-700">Target date</span>
        <span class="text-sm text-secondary">
          {{ shortDate(budget.targetDate) }}
        </span>
      </div>
      <div class="flex items-center gap-3 px-4 py-3">
        <IconClock class="h-4 w-4 flex-none text-neutral-400" />
        <span class="flex-1 text-sm text-neutral-700">Funding schedule</span>
        <span class="text-right text-sm text-secondary">
          {{ schedule(budget.fundingSchedule) }}
        </span>
      </div>
    </template>

    <!-- Capped-specific rows -->
    <template v-else-if="budget.budgetType === 'C'">
      <div
        class="flex items-center gap-3 border-b border-neutral-100 px-4 py-3"
      >
        <IconTarget class="h-4 w-4 flex-none text-neutral-400" />
        <span class="flex-1 text-sm text-neutral-700">Cap</span>
        <MoneyAmount
          v-if="budget.targetBalance"
          :amount="budget.targetBalance"
          size="md"
        />
        <span v-else class="text-sm text-secondary">—</span>
      </div>
      <div
        class="flex items-center gap-3 border-b border-neutral-100 px-4 py-3"
      >
        <IconCoin class="h-4 w-4 flex-none text-neutral-400" />
        <span class="flex-1 text-sm text-neutral-700">Amount per event</span>
        <MoneyAmount
          v-if="budget.fundingAmount"
          :amount="budget.fundingAmount"
          size="md"
        />
        <span v-else class="text-sm text-secondary">—</span>
      </div>
      <div class="flex items-center gap-3 px-4 py-3">
        <IconClock class="h-4 w-4 flex-none text-neutral-400" />
        <span class="flex-1 text-sm text-neutral-700">Funding schedule</span>
        <span class="text-right text-sm text-secondary">
          {{ schedule(budget.fundingSchedule) }}
        </span>
      </div>
    </template>

    <!-- Recurring-specific rows -->
    <template v-else>
      <div
        class="flex items-center gap-3 border-b border-neutral-100 px-4 py-3"
      >
        <IconRefresh class="h-4 w-4 flex-none text-neutral-400" />
        <span class="flex-1 text-sm text-neutral-700">Refresh cycle</span>
        <span class="text-right text-sm text-secondary">
          {{ schedule(budget.recurrenceSchedule) }}
        </span>
      </div>
      <div
        class="flex items-center gap-3 border-b border-neutral-100 px-4 py-3"
      >
        <IconCalendar class="h-4 w-4 flex-none text-neutral-400" />
        <span class="flex-1 text-sm text-neutral-700">Next refresh</span>
        <span class="text-sm text-secondary">
          {{ shortDate(budget.nextRecurrence) }}
        </span>
      </div>
      <div
        class="flex items-center gap-3 border-b border-neutral-100 px-4 py-3"
      >
        <IconClock class="h-4 w-4 flex-none text-neutral-400" />
        <span class="flex-1 text-sm text-neutral-700">Funding schedule</span>
        <span class="text-right text-sm text-secondary">
          {{ schedule(budget.fundingSchedule) }}
        </span>
      </div>
      <div
        class="flex items-center gap-3 border-b border-neutral-100 px-4 py-3"
      >
        <IconTarget class="h-4 w-4 flex-none text-neutral-400" />
        <span class="flex-1 text-sm text-neutral-700">Target amount</span>
        <MoneyAmount
          v-if="budget.targetBalance"
          :amount="budget.targetBalance"
          size="md"
        />
        <span v-else class="text-sm text-secondary">—</span>
      </div>
    </template>

    <!-- Next funding row — shown for any budget that has an upcoming event -->
    <div
      v-if="nextFunding"
      class="flex items-start gap-3 border-t border-neutral-100 px-4 py-3"
    >
      <IconCalendar class="mt-0.5 h-4 w-4 flex-none text-neutral-400" />
      <div class="flex-1">
        <span class="text-sm text-neutral-700"> Next fill-up deposit </span>
      </div>
      <div class="text-right">
        <MoneyAmount :amount="nextFunding.amount" size="md" />
        <div class="mt-0.5 text-xs text-secondary">
          {{ shortDate(nextFunding.date) }}
          <span v-if="nextFunding.daysAway === 0">(today)</span>
          <span v-else-if="nextFunding.daysAway === 1">(tomorrow)</span>
          <span v-else-if="nextFunding.daysAway > 0">
            (in {{ nextFunding.daysAway }} days)
          </span>
          <span v-else>({{ Math.abs(nextFunding.daysAway) }} days ago)</span>
        </div>
      </div>
    </div>
  </section>
</template>
