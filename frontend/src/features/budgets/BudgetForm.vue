<script setup lang="ts">
//
// BudgetForm — create and edit form for budgets.  (UI_SPEC §4.3, §4.4)
// Feature component (budgets); state and saving live in
// `useBudgetForm`.
//
// Create mode: type selector shown, bank account taken from the
//   account context, all fields editable.
// Edit mode: type selector hidden, bank account and budget type shown
//   as read-only, other fields editable.
//
// Emits `saved(budget)` on success, `cancel` on dismiss.
//

// 3rd party imports
//
import { IconBucket, IconRepeat, IconTarget } from "@tabler/icons-vue";

// app imports
//
import SchedulePicker from "@/components/budgets/SchedulePicker.vue";
import type { Budget } from "@/models/budget";
import { useBudgetForm } from "./useBudgetForm";

////////////////////////////////////////////////////////////////////////
//
interface Props {
  mode: "create" | "edit";
  budget?: Budget;
}

const props = defineProps<Props>();
const emit = defineEmits<{
  (e: "saved", budget: Budget): void;
  (e: "cancel"): void;
}>();

const {
  budgetType,
  name,
  targetBalance,
  targetDate,
  fundingType,
  fundingAmount,
  fundingSchedule,
  recurrenceSchedule,
  nextRefreshDate,
  paused,
  saving,
  isGoal,
  isRecurring,
  isCapped,
  canSubmit,
  accountName,
  error,
  submit: save,
} = useBudgetForm(props.mode, props.budget);

////////////////////////////////////////////////////////////////////////
//
async function submit() {
  const saved = await save();
  if (saved) emit("saved", saved);
}
</script>

<template>
  <form class="space-y-4" @submit.prevent="submit">
    <!-- Type selector (create only) -->
    <div v-if="mode === 'create'" class="grid grid-cols-3 gap-2">
      <button
        type="button"
        class="rounded-card border-2 px-3 py-3 text-left transition-colors"
        :class="
          budgetType === 'G'
            ? 'border-accent-border bg-accent-subtle'
            : 'border-border bg-surface hover:border-border-emphasis'
        "
        @click="budgetType = 'G'"
      >
        <IconTarget
          class="h-5 w-5"
          :class="budgetType === 'G' ? 'text-accent-fg' : 'text-icon-muted'"
        />
        <div class="mt-1 text-[14px] font-medium text-fg">Goal</div>
        <div class="mt-0.5 text-[11px] text-fg-muted">Save toward a target</div>
      </button>
      <button
        type="button"
        class="rounded-card border-2 px-3 py-3 text-left transition-colors"
        :class="
          budgetType === 'R'
            ? 'border-accent-border bg-accent-subtle'
            : 'border-border bg-surface hover:border-border-emphasis'
        "
        @click="budgetType = 'R'"
      >
        <IconRepeat
          class="h-5 w-5"
          :class="budgetType === 'R' ? 'text-accent-fg' : 'text-icon-muted'"
        />
        <div class="mt-1 text-[14px] font-medium text-fg">Recurring</div>
        <div class="mt-0.5 text-[11px] text-fg-muted">
          Refills on a schedule
        </div>
      </button>
      <button
        type="button"
        class="rounded-card border-2 px-3 py-3 text-left transition-colors"
        :class="
          budgetType === 'C'
            ? 'border-accent-border bg-accent-subtle'
            : 'border-border bg-surface hover:border-border-emphasis'
        "
        @click="budgetType = 'C'"
      >
        <IconBucket
          class="h-5 w-5"
          :class="budgetType === 'C' ? 'text-accent-fg' : 'text-icon-muted'"
        />
        <div class="mt-1 text-[14px] font-medium text-fg">Capped</div>
        <div class="mt-0.5 text-[11px] text-fg-muted">Tops up to a cap</div>
      </button>
    </div>

    <!-- Read-only type + account in edit mode -->
    <div v-if="mode === 'edit'" class="space-y-1">
      <div
        class="flex items-center justify-between rounded-subcard bg-surface-sunken px-4 py-3"
      >
        <span class="text-sm text-fg-muted">Type</span>
        <span class="text-sm font-medium text-fg">
          {{ budget?.budgetType === "G" ? "Goal" : "Recurring" }}
        </span>
      </div>
      <div
        class="flex items-center justify-between rounded-subcard bg-surface-sunken px-4 py-3"
      >
        <span class="text-sm text-fg-muted">Account</span>
        <span class="text-sm font-medium text-fg">
          {{ accountName }}
        </span>
      </div>
    </div>

    <!-- Name -->
    <div>
      <label
        class="mb-1 block text-[13px] font-medium text-fg"
        for="budget-name"
      >
        Name
      </label>
      <input
        id="budget-name"
        v-model="name"
        type="text"
        required
        placeholder="e.g. Groceries"
        class="w-full rounded-subcard border border-border-strong px-3 py-2.5 text-[15px] text-fg placeholder-fg-subtle focus:border-border-focus focus:outline-none"
      />
    </div>

    <!-- Target amount (both types) -->
    <div>
      <label
        class="mb-1 block text-[13px] font-medium text-fg"
        for="target-balance"
      >
        Target amount
      </label>
      <input
        id="target-balance"
        v-model="targetBalance"
        type="number"
        min="0"
        step="0.01"
        placeholder="0.00"
        class="w-full rounded-subcard border border-border-strong px-3 py-2.5 font-mono text-[15px] text-fg placeholder-fg-subtle focus:border-border-focus focus:outline-none"
      />
    </div>

    <!-- Goal-specific fields -->
    <template v-if="isGoal">
      <!-- Funding type toggle -->
      <div>
        <p class="mb-1.5 text-[13px] font-medium text-fg">Funding type</p>
        <div class="flex gap-2">
          <button
            type="button"
            class="flex-1 rounded-full border py-2 text-sm font-medium transition-colors"
            :class="
              fundingType === 'D'
                ? 'border-accent-border bg-accent-subtle text-accent-fg'
                : 'border-border bg-surface text-fg-muted hover:border-border-emphasis'
            "
            @click="fundingType = 'D'"
          >
            Target date
          </button>
          <button
            type="button"
            class="flex-1 rounded-full border py-2 text-sm font-medium transition-colors"
            :class="
              fundingType === 'F'
                ? 'border-accent-border bg-accent-subtle text-accent-fg'
                : 'border-border bg-surface text-fg-muted hover:border-border-emphasis'
            "
            @click="fundingType = 'F'"
          >
            Fixed amount
          </button>
        </div>
      </div>

      <template v-if="fundingType === 'D'">
        <div>
          <label
            class="mb-1 block text-[13px] font-medium text-fg"
            for="target-date"
          >
            Target date
          </label>
          <input
            id="target-date"
            v-model="targetDate"
            type="date"
            class="w-full rounded-subcard border border-border-strong px-3 py-2.5 text-[15px] text-fg focus:border-border-focus focus:outline-none"
          />
        </div>
      </template>

      <template v-else>
        <div>
          <label
            class="mb-1 block text-[13px] font-medium text-fg"
            for="funding-amount"
          >
            Amount per funding event
          </label>
          <input
            id="funding-amount"
            v-model="fundingAmount"
            type="number"
            min="0"
            step="0.01"
            placeholder="0.00"
            class="w-full rounded-subcard border border-border-strong px-3 py-2.5 font-mono text-[15px] text-fg placeholder-fg-subtle focus:border-border-focus focus:outline-none"
          />
        </div>
      </template>

      <SchedulePicker v-model="fundingSchedule" label="Funding schedule" />
    </template>

    <!-- Capped-specific fields -->
    <template v-else-if="isCapped">
      <p class="rounded-subcard bg-info-bg px-3 py-2 text-[12px] text-info-fg">
        Funds a fixed amount on a schedule up to the cap above. Resumes
        automatically whenever spending brings the balance below the cap.
      </p>
      <div>
        <label
          class="mb-1 block text-[13px] font-medium text-fg"
          for="funding-amount"
        >
          Amount per funding event
        </label>
        <input
          id="funding-amount"
          v-model="fundingAmount"
          type="number"
          min="0"
          step="0.01"
          placeholder="0.00"
          class="w-full rounded-subcard border border-border-strong px-3 py-2.5 font-mono text-[15px] text-fg placeholder-fg-subtle focus:border-border-focus focus:outline-none"
        />
      </div>
      <SchedulePicker v-model="fundingSchedule" label="Funding schedule" />

      <!-- Start paused toggle -->
      <label
        class="flex cursor-pointer items-center justify-between rounded-subcard border border-border bg-surface px-4 py-3"
      >
        <div class="text-[15px] font-medium text-fg">Start paused</div>
        <div class="relative">
          <input v-model="paused" type="checkbox" class="sr-only" />
          <div
            class="h-6 w-10 rounded-full transition-colors"
            :class="paused ? 'bg-accent' : 'bg-border-strong'"
          />
          <div
            class="absolute top-0.5 h-5 w-5 rounded-full bg-surface shadow transition-transform"
            :class="paused ? 'translate-x-4' : 'translate-x-0.5'"
          />
        </div>
      </label>
    </template>

    <!-- Recurring-specific fields -->
    <template v-else-if="isRecurring">
      <SchedulePicker
        v-model="recurrenceSchedule"
        label="Refresh cycle"
        interval-only
      />

      <!-- Next refresh date (stored as DTSTART in recurrence_schedule) -->
      <div>
        <label
          class="mb-1 block text-[13px] font-medium text-fg"
          for="next-refresh-date"
        >
          Next refresh date
        </label>
        <p class="mb-1.5 text-[11px] text-fg-muted">
          When the budgeted expense next hits and the budget refreshes
        </p>
        <input
          id="next-refresh-date"
          v-model="nextRefreshDate"
          type="date"
          class="w-full rounded-subcard border border-border-strong px-3 py-2.5 text-[15px] text-fg focus:border-border-focus focus:outline-none"
        />
      </div>

      <SchedulePicker v-model="fundingSchedule" label="Funding schedule" />

      <!-- Start paused toggle -->
      <label
        class="flex cursor-pointer items-center justify-between rounded-subcard border border-border bg-surface px-4 py-3"
      >
        <div class="text-[15px] font-medium text-fg">Start paused</div>
        <div class="relative">
          <input v-model="paused" type="checkbox" class="sr-only" />
          <div
            class="h-6 w-10 rounded-full transition-colors"
            :class="paused ? 'bg-accent' : 'bg-border-strong'"
          />
          <div
            class="absolute top-0.5 h-5 w-5 rounded-full bg-surface shadow transition-transform"
            :class="paused ? 'translate-x-4' : 'translate-x-0.5'"
          />
        </div>
      </label>
    </template>

    <!-- Error -->
    <p
      v-if="error"
      class="rounded-subcard bg-danger-bg px-4 py-2 text-sm text-danger-fg"
    >
      {{ error }}
    </p>

    <!-- Actions -->
    <div class="flex gap-2 pt-2">
      <button
        type="button"
        class="flex-1 rounded-full border border-border py-3 text-sm font-medium text-fg hover:bg-surface-sunken"
        @click="emit('cancel')"
      >
        Cancel
      </button>
      <button
        type="submit"
        :disabled="!canSubmit"
        class="flex-1 rounded-full py-3 text-sm font-medium text-fg-on-accent transition-colors"
        :class="
          canSubmit
            ? 'bg-accent hover:bg-accent-hover'
            : 'cursor-not-allowed bg-surface-strong'
        "
      >
        {{ saving ? "Saving…" : mode === "create" ? "Create" : "Save" }}
      </button>
    </div>
  </form>
</template>
