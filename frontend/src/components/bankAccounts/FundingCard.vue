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
  <section
    class="overflow-hidden rounded-card border border-neutral-200 bg-white"
  >
    <h2
      class="border-b border-neutral-100 px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-secondary"
    >
      Funding
    </h2>
    <div class="px-4 py-3 space-y-3">
      <div class="flex items-center justify-between text-sm">
        <span class="text-secondary">Data current through</span>
        <span class="font-mono text-neutral-900">
          {{ lastPostedThrough ?? "—" }}
        </span>
      </div>
      <p class="text-xs text-secondary">
        After importing transactions and finishing allocations, run the funding
        engine to move money into budgets based on their schedules.
      </p>
      <div
        v-if="summary && !summary.total.isZero()"
        class="rounded-subcard border border-ocean-200 bg-ocean-50 px-3 py-2 text-xs text-ocean-700"
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
          <p class="text-sm text-neutral-900">Automatic funding</p>
          <p class="mt-0.5 text-xs text-secondary">
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
            class="h-6 w-10 rounded-full transition-colors"
            :class="autoFundingEnabled ? 'bg-ocean-400' : 'bg-neutral-300'"
          />
          <div
            class="absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform"
            :class="autoFundingEnabled ? 'translate-x-4' : 'translate-x-0.5'"
          />
        </div>
      </label>

      <button
        type="button"
        :disabled="running"
        class="w-full rounded-subcard bg-ocean-400 py-2.5 text-sm font-medium text-white hover:bg-ocean-600 disabled:opacity-50"
        @click="emit('run')"
      >
        {{ running ? "Running…" : "Run funding now" }}
      </button>

      <!-- Result -->
      <div
        v-if="result"
        class="rounded-subcard border px-3 py-2.5 text-sm"
        :class="
          nothingDue
            ? 'border-neutral-200 bg-neutral-50 text-neutral-600'
            : 'border-mint-200 bg-mint-50 text-mint-700'
        "
      >
        <template v-if="nothingDue">
          Nothing currently due.
          <span v-if="nextDate" class="text-neutral-500">
            Next funding event: {{ nextDate }}.
          </span>
        </template>
        <template v-else>
          {{ result.transfers }} transfer{{ result.transfers === 1 ? "" : "s" }}
          completed.
        </template>
        <ul
          v-if="result.warnings.length"
          class="mt-1.5 space-y-0.5 text-xs text-amber-600"
        >
          <li v-for="w in result.warnings" :key="w">{{ w }}</li>
        </ul>
        <div v-if="result.skippedBudgets.length" class="mt-1.5">
          <span class="text-xs font-medium">Skipped (paused):</span>
          <ul class="mt-0.5 space-y-0.5 text-xs opacity-80">
            <li v-for="name in result.skippedBudgets" :key="name">
              {{ name }}
            </li>
          </ul>
        </div>
      </div>
      <div
        v-if="error"
        class="rounded-subcard border border-coral-200 bg-coral-50 px-3 py-2.5 text-sm text-coral-600"
      >
        {{ error }}
      </div>
    </div>
  </section>
</template>
