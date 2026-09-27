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
  <section class="overflow-hidden rounded-card border border-border bg-surface">
    <h2
      class="border-b border-border-subtle px-4 py-3 text-overline uppercase text-fg-muted"
    >
      Configuration
    </h2>

    <!-- Goal-specific rows -->
    <template v-if="budget.budgetType === 'G'">
      <div
        class="flex items-center gap-3 border-b border-border-subtle px-4 py-3"
      >
        <IconTarget class="size-icon-sm flex-none text-icon-muted" />
        <span class="flex-1 text-body-sm text-fg">Target amount</span>
        <MoneyAmount
          v-if="budget.targetBalance"
          :amount="budget.targetBalance"
          size="md"
        />
        <span v-else class="text-body-sm text-fg-muted">—</span>
      </div>
      <div
        class="flex items-center gap-3 border-b border-border-subtle px-4 py-3"
      >
        <IconCalendar class="size-icon-sm flex-none text-icon-muted" />
        <span class="flex-1 text-body-sm text-fg">Target date</span>
        <span class="text-body-sm text-fg-muted">
          {{ shortDate(budget.targetDate) }}
        </span>
      </div>
      <div class="flex items-center gap-3 px-4 py-3">
        <IconClock class="size-icon-sm flex-none text-icon-muted" />
        <span class="flex-1 text-body-sm text-fg">Funding schedule</span>
        <span class="text-right text-body-sm text-fg-muted">
          {{ schedule(budget.fundingSchedule) }}
        </span>
      </div>
    </template>

    <!-- Capped-specific rows -->
    <template v-else-if="budget.budgetType === 'C'">
      <div
        class="flex items-center gap-3 border-b border-border-subtle px-4 py-3"
      >
        <IconTarget class="size-icon-sm flex-none text-icon-muted" />
        <span class="flex-1 text-body-sm text-fg">Cap</span>
        <MoneyAmount
          v-if="budget.targetBalance"
          :amount="budget.targetBalance"
          size="md"
        />
        <span v-else class="text-body-sm text-fg-muted">—</span>
      </div>
      <div
        class="flex items-center gap-3 border-b border-border-subtle px-4 py-3"
      >
        <IconCoin class="size-icon-sm flex-none text-icon-muted" />
        <span class="flex-1 text-body-sm text-fg">Amount per event</span>
        <MoneyAmount
          v-if="budget.fundingAmount"
          :amount="budget.fundingAmount"
          size="md"
        />
        <span v-else class="text-body-sm text-fg-muted">—</span>
      </div>
      <div class="flex items-center gap-3 px-4 py-3">
        <IconClock class="size-icon-sm flex-none text-icon-muted" />
        <span class="flex-1 text-body-sm text-fg">Funding schedule</span>
        <span class="text-right text-body-sm text-fg-muted">
          {{ schedule(budget.fundingSchedule) }}
        </span>
      </div>
    </template>

    <!-- Recurring-specific rows -->
    <template v-else>
      <div
        class="flex items-center gap-3 border-b border-border-subtle px-4 py-3"
      >
        <IconRefresh class="size-icon-sm flex-none text-icon-muted" />
        <span class="flex-1 text-body-sm text-fg">Refresh cycle</span>
        <span class="text-right text-body-sm text-fg-muted">
          {{ schedule(budget.recurrenceSchedule) }}
        </span>
      </div>
      <div
        class="flex items-center gap-3 border-b border-border-subtle px-4 py-3"
      >
        <IconCalendar class="size-icon-sm flex-none text-icon-muted" />
        <span class="flex-1 text-body-sm text-fg">Next refresh</span>
        <span class="text-body-sm text-fg-muted">
          {{ shortDate(budget.nextRecurrence) }}
        </span>
      </div>
      <div
        class="flex items-center gap-3 border-b border-border-subtle px-4 py-3"
      >
        <IconClock class="size-icon-sm flex-none text-icon-muted" />
        <span class="flex-1 text-body-sm text-fg">Funding schedule</span>
        <span class="text-right text-body-sm text-fg-muted">
          {{ schedule(budget.fundingSchedule) }}
        </span>
      </div>
      <div
        class="flex items-center gap-3 border-b border-border-subtle px-4 py-3"
      >
        <IconTarget class="size-icon-sm flex-none text-icon-muted" />
        <span class="flex-1 text-body-sm text-fg">Target amount</span>
        <MoneyAmount
          v-if="budget.targetBalance"
          :amount="budget.targetBalance"
          size="md"
        />
        <span v-else class="text-body-sm text-fg-muted">—</span>
      </div>
    </template>

    <!-- Next funding row — shown for any budget that has an upcoming event -->
    <div
      v-if="nextFunding"
      class="flex items-start gap-3 border-t border-border-subtle px-4 py-3"
    >
      <IconCalendar class="mt-0.5 size-icon-sm flex-none text-icon-muted" />
      <div class="flex-1">
        <span class="text-body-sm text-fg"> Next fill-up deposit </span>
      </div>
      <div class="text-right">
        <MoneyAmount :amount="nextFunding.amount" size="md" />
        <div class="mt-0.5 text-meta text-fg-muted">
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
