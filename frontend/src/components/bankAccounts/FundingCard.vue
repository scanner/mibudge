<script setup lang="ts">
//
// FundingCard — the bank-account page's funding controls: data
// freshness, the next funding event, the automatic-funding switch, and
// "Run funding now" with its result.  Presentational: emits
// `toggle-auto-funding` and `run`.
//

// app imports
//
import MoneyAmount from "@/components/base/MoneyAmount.vue";
import { formatLocalDate } from "@/domain/dates";
import type { LocalDate } from "@/domain/dates";
import type { FundingRunResult, FundingSummary } from "@/models/bankAccount";
import BaseButton from "@/components/base/BaseButton.vue";
import BaseToggle from "@/components/base/BaseToggle.vue";
import BaseSectionHeader from "@/components/base/BaseSectionHeader.vue";
import BaseCard from "@/components/base/BaseCard.vue";
import BaseCardSection from "@/components/base/BaseCardSection.vue";
import BaseBanner from "@/components/base/BaseBanner.vue";

////////////////////////////////////////////////////////////////////////
//
defineProps<{
  lastPostedThrough: LocalDate | null;
  summary: FundingSummary | null;
  autoFundingEnabled: boolean;
  running: boolean;
  result: FundingRunResult | null;
  // True when the run moved nothing and reported nothing.
  nothingDue: boolean;
  nextDate: LocalDate | null;
  error: string | null;
}>();

const emit = defineEmits<{
  (e: "toggle-auto-funding"): void;
  (e: "run"): void;
}>();
</script>

<template>
  <!-- Funding -->
  <BaseCard as="section">
    <BaseSectionHeader title="Funding" card />
    <BaseCardSection class="space-y-3">
      <div class="flex items-center justify-between text-body-sm">
        <span class="text-fg-muted">Data current through</span>
        <span class="text-fg">
          {{
            lastPostedThrough ? formatLocalDate(lastPostedThrough, "date") : "—"
          }}
        </span>
      </div>
      <p class="text-meta text-fg-muted">
        After importing transactions and finishing allocations, run the funding
        engine to move money into budgets based on their schedules.
      </p>
      <BaseBanner v-if="summary && !summary.total.isZero()" tone="info">
        Next event:
        <MoneyAmount :amount="summary.total" size="sm" />
        <template v-if="summary.schedules[0]?.nextDate">
          on {{ formatLocalDate(summary.schedules[0].nextDate, "date") }}
        </template>
        <template v-if="summary.schedules.length > 1">
          across {{ summary.schedules.length }} schedules
        </template>
      </BaseBanner>
      <!-- Automatic funding toggle -->
      <label class="flex cursor-pointer items-center justify-between">
        <div>
          <p class="text-body-sm text-fg">Automatic funding</p>
          <p class="mt-0.5 text-meta text-fg-muted">
            Run funding events on a schedule. Disable to fund manually only.
          </p>
        </div>
        <div class="ml-4 flex-none">
          <BaseToggle
            :model-value="autoFundingEnabled"
            @update:model-value="emit('toggle-auto-funding')"
          />
        </div>
      </label>

      <BaseButton block :loading="running" @click="emit('run')">
        {{ running ? "Running…" : "Run funding now" }}
      </BaseButton>

      <!-- Result -->
      <div
        v-if="result"
        class="rounded-control border px-3 py-2.5 text-body-sm"
        :class="
          nothingDue
            ? 'border-border bg-surface-sunken text-fg-muted'
            : 'border-success-border bg-success-bg text-success-fg'
        "
      >
        <template v-if="nothingDue">
          Nothing currently due.
          <span v-if="nextDate" class="text-fg-muted">
            Next funding event: {{ formatLocalDate(nextDate, "date") }}.
          </span>
        </template>
        <template v-else>
          {{ result.transfers }} transfer{{ result.transfers === 1 ? "" : "s" }}
          completed.
        </template>
        <ul
          v-if="result.warnings.length"
          class="mt-1.5 space-y-0.5 text-meta text-warning-fg"
        >
          <li v-for="w in result.warnings" :key="w">{{ w }}</li>
        </ul>
        <div v-if="result.skippedBudgets.length" class="mt-1.5">
          <span class="text-meta font-medium">Skipped (paused):</span>
          <ul class="mt-0.5 space-y-0.5 text-meta opacity-80">
            <li v-for="name in result.skippedBudgets" :key="name">
              {{ name }}
            </li>
          </ul>
        </div>
      </div>
      <BaseBanner v-if="error" tone="danger">
        {{ error }}
      </BaseBanner>
    </BaseCardSection>
  </BaseCard>
</template>
