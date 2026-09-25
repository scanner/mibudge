<script setup lang="ts">
//
// BudgetDetailView — full detail screen for a single budget.
// (UI_SPEC §4.3)  Route shell: reads the `id` param and composes the
// budget feature sections.
//
// Sections:
//  1. Hero block (BudgetDetailHero)
//  2. "Move money" CTA → MoveMoneySheet
//  3. Configuration card (editing via BudgetEditSheet)
//  4. Pause / archive action row
//  5. Transaction list (BudgetTransactionsSection)
//
// Everything follows the `id` prop, so the route reused with a new id
// shows the new budget.
//

// 3rd party imports
//
import {
  IconArchive,
  IconArrowsRightLeft,
  IconPencil,
  IconPlayerPause,
} from "@tabler/icons-vue";
import { computed, ref, watch } from "vue";
import { useRouter } from "vue-router";

// app imports
//
import BudgetConfigSection from "@/components/budgets/BudgetConfigSection.vue";
import BudgetDetailHero from "@/components/budgets/BudgetDetailHero.vue";
import ConfirmSheet from "@/components/shared/ConfirmSheet.vue";
import { todayDateStr } from "@/domain/dates";
import BudgetEditSheet from "@/features/budgets/BudgetEditSheet.vue";
import BudgetTransactionsSection from "@/features/budgets/BudgetTransactionsSection.vue";
import MoveMoneySheet from "@/features/budgets/MoveMoneySheet.vue";
import { useBudgetDetail } from "@/features/budgets/useBudgetDetail";
import AppShell from "@/features/shell/AppShell.vue";
import { useSessionStore } from "@/stores/session";

////////////////////////////////////////////////////////////////////////
//
const props = defineProps<{ id: string }>();
const router = useRouter();
const session = useSessionStore();

const {
  budget,
  fillupBudget,
  isUnallocated,
  accountName,
  loading,
  error: loadError,
  actionError,
  togglePause,
  archive,
} = useBudgetDetail(() => props.id);

const error = computed(() => loadError.value ?? actionError.value);
const today = computed(() => todayDateStr(session.timezone));

const showEditSheet = ref(false);
const showArchiveConfirm = ref(false);
const showMoveMoneyForm = ref(false);

// A different budget closes any sheet opened for the previous one.
watch(
  () => props.id,
  () => {
    showEditSheet.value = false;
    showArchiveConfirm.value = false;
    showMoveMoneyForm.value = false;
  },
);

////////////////////////////////////////////////////////////////////////
//
async function confirmArchive() {
  showArchiveConfirm.value = false;
  if (await archive()) router.push({ name: "budgets" });
}
</script>

<template>
  <AppShell>
    <template #action>
      <button
        v-if="budget && !isUnallocated"
        type="button"
        class="flex h-10 items-center rounded-full px-3 text-sm font-medium text-ocean-600 hover:bg-ocean-50"
        @click="showEditSheet = true"
      >
        <IconPencil class="mr-1 h-4 w-4" />
        Edit
      </button>
    </template>

    <!-- Loading skeleton -->
    <div v-if="loading" class="space-y-4 pt-4">
      <div class="h-48 animate-pulse rounded-card bg-neutral-100" />
      <div class="h-14 animate-pulse rounded-card bg-neutral-100" />
      <div class="h-32 animate-pulse rounded-card bg-neutral-100" />
    </div>

    <!-- Error -->
    <div
      v-else-if="error && !budget"
      class="mt-4 rounded-card bg-coral-50 px-4 py-3 text-sm text-coral-600"
    >
      {{ error }}
    </div>

    <template v-else-if="budget">
      <div class="space-y-4 pt-4">
        <!-- Hero -->
        <BudgetDetailHero
          :budget="budget"
          :account-name="accountName"
          :fillup-budget="fillupBudget ?? undefined"
        />

        <!-- Move money CTA (not for unallocated budget) -->
        <button
          v-if="!isUnallocated"
          type="button"
          class="flex w-full items-start gap-3 rounded-card border border-neutral-200 bg-ocean-50 px-4 py-3 text-left"
          @click="showMoveMoneyForm = true"
        >
          <IconArrowsRightLeft
            class="mt-0.5 h-5 w-5 flex-none text-ocean-400"
          />
          <div>
            <div class="text-[15px] font-medium text-ocean-600">Move money</div>
            <div class="text-xs text-secondary">
              Transfer to or from another budget
            </div>
          </div>
        </button>

        <!-- Configuration section -->
        <BudgetConfigSection
          v-if="!isUnallocated"
          :budget="budget"
          :fillup-budget="fillupBudget"
          :today="today"
        />

        <!-- Action row -->
        <div v-if="!isUnallocated" class="mt-2 flex gap-2">
          <button
            type="button"
            class="flex-1 rounded-full border border-neutral-200 py-3 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
            @click="togglePause"
          >
            <IconPlayerPause class="mr-1 inline-block h-4 w-4" />
            {{ budget.paused ? "Resume budget" : "Pause budget" }}
          </button>
          <button
            type="button"
            class="flex-1 rounded-full border border-neutral-200 py-3 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
            @click="showArchiveConfirm = true"
          >
            <IconArchive class="mr-1 inline-block h-4 w-4" />
            Archive
          </button>
        </div>

        <!-- Transactions section -->
        <BudgetTransactionsSection :budget-id="id" />

        <!-- Inline error banner -->
        <p
          v-if="error"
          class="rounded-subcard bg-coral-50 px-4 py-2 text-sm text-coral-600"
        >
          {{ error }}
        </p>
      </div>
    </template>

    <!-- Archive confirmation sheet -->
    <ConfirmSheet
      :open="showArchiveConfirm"
      title="Archive budget?"
      :message="`'${budget?.name}' will be hidden and any remaining balance moved to Unallocated. Transaction history is preserved.`"
      confirm-label="Archive"
      @confirm="confirmArchive"
      @cancel="showArchiveConfirm = false"
    />

    <!-- Edit sheet (full-page overlay) -->
    <BudgetEditSheet
      :open="showEditSheet"
      :budget="budget"
      @saved="showEditSheet = false"
      @close="showEditSheet = false"
    />

    <!-- Move money sheet -->
    <MoveMoneySheet
      :open="showMoveMoneyForm"
      :budget="budget"
      :fillup-budget="fillupBudget"
      @close="showMoveMoneyForm = false"
    />
  </AppShell>
</template>
