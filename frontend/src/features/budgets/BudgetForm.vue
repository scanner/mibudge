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
            ? 'border-ocean-400 bg-ocean-50'
            : 'border-neutral-200 bg-white hover:border-neutral-300'
        "
        @click="budgetType = 'G'"
      >
        <IconTarget
          class="h-5 w-5"
          :class="budgetType === 'G' ? 'text-ocean-500' : 'text-neutral-400'"
        />
        <div class="mt-1 text-[14px] font-medium text-neutral-900">Goal</div>
        <div class="mt-0.5 text-[11px] text-neutral-500">
          Save toward a target
        </div>
      </button>
      <button
        type="button"
        class="rounded-card border-2 px-3 py-3 text-left transition-colors"
        :class="
          budgetType === 'R'
            ? 'border-ocean-400 bg-ocean-50'
            : 'border-neutral-200 bg-white hover:border-neutral-300'
        "
        @click="budgetType = 'R'"
      >
        <IconRepeat
          class="h-5 w-5"
          :class="budgetType === 'R' ? 'text-ocean-500' : 'text-neutral-400'"
        />
        <div class="mt-1 text-[14px] font-medium text-neutral-900">
          Recurring
        </div>
        <div class="mt-0.5 text-[11px] text-neutral-500">
          Refills on a schedule
        </div>
      </button>
      <button
        type="button"
        class="rounded-card border-2 px-3 py-3 text-left transition-colors"
        :class="
          budgetType === 'C'
            ? 'border-ocean-400 bg-ocean-50'
            : 'border-neutral-200 bg-white hover:border-neutral-300'
        "
        @click="budgetType = 'C'"
      >
        <IconBucket
          class="h-5 w-5"
          :class="budgetType === 'C' ? 'text-ocean-500' : 'text-neutral-400'"
        />
        <div class="mt-1 text-[14px] font-medium text-neutral-900">Capped</div>
        <div class="mt-0.5 text-[11px] text-neutral-500">Tops up to a cap</div>
      </button>
    </div>

    <!-- Read-only type + account in edit mode -->
    <div v-if="mode === 'edit'" class="space-y-1">
      <div
        class="flex items-center justify-between rounded-subcard bg-neutral-50 px-4 py-3"
      >
        <span class="text-sm text-neutral-500">Type</span>
        <span class="text-sm font-medium text-neutral-900">
          {{ budget?.budgetType === "G" ? "Goal" : "Recurring" }}
        </span>
      </div>
      <div
        class="flex items-center justify-between rounded-subcard bg-neutral-50 px-4 py-3"
      >
        <span class="text-sm text-neutral-500">Account</span>
        <span class="text-sm font-medium text-neutral-900">
          {{ accountName }}
        </span>
      </div>
    </div>

    <!-- Name -->
    <div>
      <label
        class="mb-1 block text-[13px] font-medium text-neutral-700"
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
        class="w-full rounded-subcard border border-neutral-200 px-3 py-2.5 text-[15px] text-neutral-900 placeholder-neutral-400 focus:border-ocean-400 focus:outline-none"
      />
    </div>

    <!-- Target amount (both types) -->
    <div>
      <label
        class="mb-1 block text-[13px] font-medium text-neutral-700"
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
        class="w-full rounded-subcard border border-neutral-200 px-3 py-2.5 font-mono text-[15px] text-neutral-900 placeholder-neutral-400 focus:border-ocean-400 focus:outline-none"
      />
    </div>

    <!-- Goal-specific fields -->
    <template v-if="isGoal">
      <!-- Funding type toggle -->
      <div>
        <p class="mb-1.5 text-[13px] font-medium text-neutral-700">
          Funding type
        </p>
        <div class="flex gap-2">
          <button
            type="button"
            class="flex-1 rounded-full border py-2 text-sm font-medium transition-colors"
            :class="
              fundingType === 'D'
                ? 'border-ocean-400 bg-ocean-50 text-ocean-600'
                : 'border-neutral-200 bg-white text-neutral-600 hover:border-neutral-300'
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
                ? 'border-ocean-400 bg-ocean-50 text-ocean-600'
                : 'border-neutral-200 bg-white text-neutral-600 hover:border-neutral-300'
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
            class="mb-1 block text-[13px] font-medium text-neutral-700"
            for="target-date"
          >
            Target date
          </label>
          <input
            id="target-date"
            v-model="targetDate"
            type="date"
            class="w-full rounded-subcard border border-neutral-200 px-3 py-2.5 text-[15px] text-neutral-900 focus:border-ocean-400 focus:outline-none"
          />
        </div>
      </template>

      <template v-else>
        <div>
          <label
            class="mb-1 block text-[13px] font-medium text-neutral-700"
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
            class="w-full rounded-subcard border border-neutral-200 px-3 py-2.5 font-mono text-[15px] text-neutral-900 placeholder-neutral-400 focus:border-ocean-400 focus:outline-none"
          />
        </div>
      </template>

      <SchedulePicker v-model="fundingSchedule" label="Funding schedule" />
    </template>

    <!-- Capped-specific fields -->
    <template v-else-if="isCapped">
      <p
        class="rounded-subcard bg-ocean-50 px-3 py-2 text-[12px] text-ocean-600"
      >
        Funds a fixed amount on a schedule up to the cap above. Resumes
        automatically whenever spending brings the balance below the cap.
      </p>
      <div>
        <label
          class="mb-1 block text-[13px] font-medium text-neutral-700"
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
          class="w-full rounded-subcard border border-neutral-200 px-3 py-2.5 font-mono text-[15px] text-neutral-900 placeholder-neutral-400 focus:border-ocean-400 focus:outline-none"
        />
      </div>
      <SchedulePicker v-model="fundingSchedule" label="Funding schedule" />

      <!-- Start paused toggle -->
      <label
        class="flex cursor-pointer items-center justify-between rounded-subcard border border-neutral-200 bg-white px-4 py-3"
      >
        <div class="text-[15px] font-medium text-neutral-900">Start paused</div>
        <div class="relative">
          <input v-model="paused" type="checkbox" class="sr-only" />
          <div
            class="h-6 w-10 rounded-full transition-colors"
            :class="paused ? 'bg-ocean-400' : 'bg-neutral-300'"
          />
          <div
            class="absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform"
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
          class="mb-1 block text-[13px] font-medium text-neutral-700"
          for="next-refresh-date"
        >
          Next refresh date
        </label>
        <p class="mb-1.5 text-[11px] text-neutral-500">
          When the budgeted expense next hits and the budget refreshes
        </p>
        <input
          id="next-refresh-date"
          v-model="nextRefreshDate"
          type="date"
          class="w-full rounded-subcard border border-neutral-200 px-3 py-2.5 text-[15px] text-neutral-900 focus:border-ocean-400 focus:outline-none"
        />
      </div>

      <SchedulePicker v-model="fundingSchedule" label="Funding schedule" />

      <!-- Start paused toggle -->
      <label
        class="flex cursor-pointer items-center justify-between rounded-subcard border border-neutral-200 bg-white px-4 py-3"
      >
        <div class="text-[15px] font-medium text-neutral-900">Start paused</div>
        <div class="relative">
          <input v-model="paused" type="checkbox" class="sr-only" />
          <div
            class="h-6 w-10 rounded-full transition-colors"
            :class="paused ? 'bg-ocean-400' : 'bg-neutral-300'"
          />
          <div
            class="absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform"
            :class="paused ? 'translate-x-4' : 'translate-x-0.5'"
          />
        </div>
      </label>
    </template>

    <!-- Error -->
    <p
      v-if="error"
      class="rounded-subcard bg-coral-50 px-4 py-2 text-sm text-coral-600"
    >
      {{ error }}
    </p>

    <!-- Actions -->
    <div class="flex gap-2 pt-2">
      <button
        type="button"
        class="flex-1 rounded-full border border-neutral-200 py-3 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
        @click="emit('cancel')"
      >
        Cancel
      </button>
      <button
        type="submit"
        :disabled="!canSubmit"
        class="flex-1 rounded-full py-3 text-sm font-medium text-white transition-colors"
        :class="
          canSubmit
            ? 'bg-ocean-400 hover:bg-ocean-600'
            : 'cursor-not-allowed bg-neutral-300'
        "
      >
        {{ saving ? "Saving…" : mode === "create" ? "Create" : "Save" }}
      </button>
    </div>
  </form>
</template>
