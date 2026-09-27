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
import MoneyAmount from "@/components/base/MoneyAmount.vue";
import type { LocalDate } from "@/domain/dates";
import { daysBetween, formatLocalDate } from "@/domain/dates";
import { rruleHuman } from "@/domain/rrule";
import type { Budget } from "@/models/budget";
import BaseSectionHeader from "@/components/base/BaseSectionHeader.vue";
import BaseCard from "@/components/base/BaseCard.vue";
import BaseListRow from "@/components/base/BaseListRow.vue";

////////////////////////////////////////////////////////////////////////
//
const props = defineProps<{
  budget: Budget;
  fillupBudget: Budget | null;
  // Today in the profile timezone.
  today: LocalDate;
}>();

function shortDate(date: LocalDate | null): string {
  return date ? formatLocalDate(date, "date") : "—";
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
  <BaseCard as="section">
    <BaseSectionHeader title="Configuration" card />

    <!-- Goal-specific rows -->
    <template v-if="budget.budgetType === 'G'">
      <BaseListRow>
        <IconTarget class="size-icon-sm flex-none text-icon-muted" />
        <span class="flex-1 text-body-sm text-fg">Target amount</span>
        <MoneyAmount
          v-if="budget.targetBalance"
          :amount="budget.targetBalance"
          size="md"
        />
        <span v-else class="text-body-sm text-fg-muted">—</span>
      </BaseListRow>
      <BaseListRow>
        <IconCalendar class="size-icon-sm flex-none text-icon-muted" />
        <span class="flex-1 text-body-sm text-fg">Target date</span>
        <span class="text-body-sm text-fg-muted">
          {{ shortDate(budget.targetDate) }}
        </span>
      </BaseListRow>
      <BaseListRow>
        <IconClock class="size-icon-sm flex-none text-icon-muted" />
        <span class="flex-1 text-body-sm text-fg">Funding schedule</span>
        <span class="text-right text-body-sm text-fg-muted">
          {{ schedule(budget.fundingSchedule) }}
        </span>
      </BaseListRow>
    </template>

    <!-- Capped-specific rows -->
    <template v-else-if="budget.budgetType === 'C'">
      <BaseListRow>
        <IconTarget class="size-icon-sm flex-none text-icon-muted" />
        <span class="flex-1 text-body-sm text-fg">Cap</span>
        <MoneyAmount
          v-if="budget.targetBalance"
          :amount="budget.targetBalance"
          size="md"
        />
        <span v-else class="text-body-sm text-fg-muted">—</span>
      </BaseListRow>
      <BaseListRow>
        <IconCoin class="size-icon-sm flex-none text-icon-muted" />
        <span class="flex-1 text-body-sm text-fg">Amount per event</span>
        <MoneyAmount
          v-if="budget.fundingAmount"
          :amount="budget.fundingAmount"
          size="md"
        />
        <span v-else class="text-body-sm text-fg-muted">—</span>
      </BaseListRow>
      <BaseListRow>
        <IconClock class="size-icon-sm flex-none text-icon-muted" />
        <span class="flex-1 text-body-sm text-fg">Funding schedule</span>
        <span class="text-right text-body-sm text-fg-muted">
          {{ schedule(budget.fundingSchedule) }}
        </span>
      </BaseListRow>
    </template>

    <!-- Recurring-specific rows -->
    <template v-else>
      <BaseListRow>
        <IconRefresh class="size-icon-sm flex-none text-icon-muted" />
        <span class="flex-1 text-body-sm text-fg">Refresh cycle</span>
        <span class="text-right text-body-sm text-fg-muted">
          {{ schedule(budget.recurrenceSchedule) }}
        </span>
      </BaseListRow>
      <BaseListRow>
        <IconCalendar class="size-icon-sm flex-none text-icon-muted" />
        <span class="flex-1 text-body-sm text-fg">Next refresh</span>
        <span class="text-body-sm text-fg-muted">
          {{ shortDate(budget.nextRecurrence) }}
        </span>
      </BaseListRow>
      <BaseListRow>
        <IconClock class="size-icon-sm flex-none text-icon-muted" />
        <span class="flex-1 text-body-sm text-fg">Funding schedule</span>
        <span class="text-right text-body-sm text-fg-muted">
          {{ schedule(budget.fundingSchedule) }}
        </span>
      </BaseListRow>
      <BaseListRow>
        <IconTarget class="size-icon-sm flex-none text-icon-muted" />
        <span class="flex-1 text-body-sm text-fg">Target amount</span>
        <MoneyAmount
          v-if="budget.targetBalance"
          :amount="budget.targetBalance"
          size="md"
        />
        <span v-else class="text-body-sm text-fg-muted">—</span>
      </BaseListRow>
    </template>

    <!-- Next funding row — shown for any budget that has an upcoming event -->
    <BaseListRow v-if="nextFunding" align="start">
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
    </BaseListRow>
  </BaseCard>
</template>
