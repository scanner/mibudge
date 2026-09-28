<script setup lang="ts">
//
// BudgetForm — create and edit form for budgets.
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
import BaseButton from "@/components/base/BaseButton.vue";
import BaseFormField from "@/components/base/BaseFormField.vue";
import BaseInput from "@/components/base/BaseInput.vue";
import BaseToggle from "@/components/base/BaseToggle.vue";
import BaseBanner from "@/components/base/BaseBanner.vue";

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
          class="size-icon-md"
          :class="budgetType === 'G' ? 'text-accent-fg' : 'text-icon-muted'"
        />
        <div class="mt-1 text-body font-medium text-fg">Goal</div>
        <div class="mt-0.5 text-meta text-fg-muted">Save toward a target</div>
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
          class="size-icon-md"
          :class="budgetType === 'R' ? 'text-accent-fg' : 'text-icon-muted'"
        />
        <div class="mt-1 text-body font-medium text-fg">Recurring</div>
        <div class="mt-0.5 text-meta text-fg-muted">Refills on a schedule</div>
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
          class="size-icon-md"
          :class="budgetType === 'C' ? 'text-accent-fg' : 'text-icon-muted'"
        />
        <div class="mt-1 text-body font-medium text-fg">Capped</div>
        <div class="mt-0.5 text-meta text-fg-muted">Tops up to a cap</div>
      </button>
    </div>

    <!-- Read-only type + account in edit mode -->
    <div v-if="mode === 'edit'" class="space-y-1">
      <div
        class="flex items-center justify-between rounded-control bg-surface-sunken px-4 py-3"
      >
        <span class="text-body-sm text-fg-muted">Type</span>
        <span class="text-label text-fg">
          {{ budget?.budgetType === "G" ? "Goal" : "Recurring" }}
        </span>
      </div>
      <div
        class="flex items-center justify-between rounded-control bg-surface-sunken px-4 py-3"
      >
        <span class="text-body-sm text-fg-muted">Account</span>
        <span class="text-label text-fg">
          {{ accountName }}
        </span>
      </div>
    </div>

    <!-- Name -->
    <div>
      <BaseFormField id="budget-name" label="Name">
        <template #default="{ id, describedBy, invalid }">
          <BaseInput
            :id="id"
            v-model="name"
            type="text"
            required
            placeholder="e.g. Groceries"
            :aria-describedby="describedBy"
            :invalid="invalid"
          />
        </template>
      </BaseFormField>
    </div>

    <!-- Target amount (both types) -->
    <div>
      <BaseFormField id="target-balance" label="Target amount">
        <template #default="{ id, describedBy, invalid }">
          <BaseInput
            :id="id"
            v-model="targetBalance"
            type="number"
            min="0"
            step="0.01"
            placeholder="0.00"
            :aria-describedby="describedBy"
            :invalid="invalid"
            mono
          />
        </template>
      </BaseFormField>
    </div>

    <!-- Goal-specific fields -->
    <template v-if="isGoal">
      <!-- Funding type toggle -->
      <div>
        <p class="mb-1.5 text-label text-fg">Funding type</p>
        <div class="flex gap-2">
          <button
            type="button"
            class="flex-1 rounded-pill border py-2 text-label transition-colors"
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
            class="flex-1 rounded-pill border py-2 text-label transition-colors"
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
          <BaseFormField id="target-date" label="Target date">
            <template #default="{ id, describedBy, invalid }">
              <BaseInput
                :id="id"
                v-model="targetDate"
                type="date"
                :aria-describedby="describedBy"
                :invalid="invalid"
              />
            </template>
          </BaseFormField>
        </div>
      </template>

      <template v-else>
        <div>
          <BaseFormField id="funding-amount" label="Amount per funding event">
            <template #default="{ id, describedBy, invalid }">
              <BaseInput
                :id="id"
                v-model="fundingAmount"
                type="number"
                min="0"
                step="0.01"
                placeholder="0.00"
                :aria-describedby="describedBy"
                :invalid="invalid"
                mono
              />
            </template>
          </BaseFormField>
        </div>
      </template>

      <SchedulePicker v-model="fundingSchedule" label="Funding schedule" />
    </template>

    <!-- Capped-specific fields -->
    <template v-else-if="isCapped">
      <BaseBanner tone="info">
        Funds a fixed amount on a schedule up to the cap above. Resumes
        automatically whenever spending brings the balance below the cap.
      </BaseBanner>
      <div>
        <BaseFormField id="funding-amount" label="Amount per funding event">
          <template #default="{ id, describedBy, invalid }">
            <BaseInput
              :id="id"
              v-model="fundingAmount"
              type="number"
              min="0"
              step="0.01"
              placeholder="0.00"
              :aria-describedby="describedBy"
              :invalid="invalid"
              mono
            />
          </template>
        </BaseFormField>
      </div>
      <SchedulePicker v-model="fundingSchedule" label="Funding schedule" />

      <!-- Start paused toggle -->
      <label
        class="flex cursor-pointer items-center justify-between rounded-control border border-border bg-surface px-4 py-3"
      >
        <div class="text-item-title text-fg">Start paused</div>
        <BaseToggle v-model="paused" />
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
        <label class="mb-1 block text-label text-fg" for="next-refresh-date">
          Next refresh date
        </label>
        <p class="mb-1.5 text-meta text-fg-muted">
          When the budgeted expense next hits and the budget refreshes
        </p>
        <BaseInput
          id="next-refresh-date"
          v-model="nextRefreshDate"
          type="date"
        />
      </div>

      <SchedulePicker v-model="fundingSchedule" label="Funding schedule" />

      <!-- Start paused toggle -->
      <label
        class="flex cursor-pointer items-center justify-between rounded-control border border-border bg-surface px-4 py-3"
      >
        <div class="text-item-title text-fg">Start paused</div>
        <BaseToggle v-model="paused" />
      </label>
    </template>

    <!-- Error -->
    <BaseBanner v-if="error" tone="danger">
      {{ error }}
    </BaseBanner>

    <!-- Actions -->
    <div class="flex gap-2 pt-2">
      <BaseButton variant="secondary" class="flex-1" @click="emit('cancel')">
        Cancel
      </BaseButton>
      <BaseButton type="submit" :disabled="!canSubmit" class="flex-1">
        {{ saving ? "Saving…" : mode === "create" ? "Create" : "Save" }}
      </BaseButton>
    </div>
  </form>
</template>
