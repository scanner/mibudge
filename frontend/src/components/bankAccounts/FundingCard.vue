<script setup lang="ts">
//
// FundingCard — the bank-account page's funding controls: data
// freshness, the next funding event, the automatic-funding switch, and
// "Run funding now" with its result.  Presentational: emits
// `toggle-auto-funding` and `run`.
//

// app imports
//
import MoneyAmount from "@/components/shared/MoneyAmount.vue";
import type { LocalDate } from "@/domain/dates";
import type { FundingRunResult, FundingSummary } from "@/models/bankAccount";

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
  <section class="overflow-hidden rounded-card border border-border bg-surface">
    <h2
      class="border-b border-border-subtle px-4 py-3 text-overline uppercase text-fg-muted"
    >
      Funding
    </h2>
    <div class="px-4 py-3 space-y-3">
      <div class="flex items-center justify-between text-body-sm">
        <span class="text-fg-muted">Data current through</span>
        <span class="font-mono text-fg">
          {{ lastPostedThrough ?? "—" }}
        </span>
      </div>
      <p class="text-meta text-fg-muted">
        After importing transactions and finishing allocations, run the funding
        engine to move money into budgets based on their schedules.
      </p>
      <div
        v-if="summary && !summary.total.isZero()"
        class="rounded-control border border-info-border bg-info-bg px-3 py-2 text-meta text-info-fg"
      >
        Next event:
        <MoneyAmount :amount="summary.total" size="sm" class="font-medium" />
        <template v-if="summary.schedules[0]?.nextDate">
          on {{ summary.schedules[0].nextDate }}
        </template>
        <template v-if="summary.schedules.length > 1">
          across {{ summary.schedules.length }} schedules
        </template>
      </div>
      <!-- Automatic funding toggle -->
      <label class="flex cursor-pointer items-center justify-between">
        <div>
          <p class="text-body-sm text-fg">Automatic funding</p>
          <p class="mt-0.5 text-meta text-fg-muted">
            Run funding events on a schedule. Disable to fund manually only.
          </p>
        </div>
        <div class="relative ml-4 flex-none">
          <input
            type="checkbox"
            class="sr-only"
            :checked="autoFundingEnabled"
            @change="emit('toggle-auto-funding')"
          />
          <div
            class="h-6 w-10 rounded-pill transition-colors"
            :class="autoFundingEnabled ? 'bg-accent' : 'bg-border-strong'"
          />
          <div
            class="absolute top-0.5 h-5 w-5 rounded-pill bg-surface shadow-control transition-transform"
            :class="autoFundingEnabled ? 'translate-x-4' : 'translate-x-0.5'"
          />
        </div>
      </label>

      <button
        type="button"
        :disabled="running"
        class="w-full rounded-control bg-accent py-2.5 text-label text-fg-on-accent hover:bg-accent-hover disabled:opacity-50"
        @click="emit('run')"
      >
        {{ running ? "Running…" : "Run funding now" }}
      </button>

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
            Next funding event: {{ nextDate }}.
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
      <div
        v-if="error"
        class="rounded-control border border-danger-border bg-danger-bg px-3 py-2.5 text-body-sm text-danger-fg"
      >
        {{ error }}
      </div>
    </div>
  </section>
</template>
