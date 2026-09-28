<script setup lang="ts">
//
// OverviewView — account health at a glance.  Route shell over
// `useOverview`.
//
// Shows the active account's posted/available/unallocated balances,
// top non-archived budgets with progress bars, and recent transactions
// with allocation info rendered by TransactionRow.
//

// 3rd party imports
//
import {
  IconBucket,
  IconChevronRight,
  IconRepeat,
  IconTarget,
} from "@tabler/icons-vue";
import { useRouter } from "vue-router";

// app imports
//
import FillUpBand from "@/components/budgets/FillUpBand.vue";
import MoneyAmount from "@/components/base/MoneyAmount.vue";
import ProgressBar from "@/components/base/ProgressBar.vue";
import StatusChip from "@/components/base/StatusChip.vue";
import TransactionRow from "@/components/transactions/TransactionRow.vue";
import {
  budgetProgress,
  budgetStatus,
  progressTone,
} from "@/domain/budgetStatus";
import { formatLocalDate } from "@/domain/dates";
import { useOverview } from "@/features/overview/useOverview";
import AppShell from "@/features/shell/AppShell.vue";
import { useAccountContextStore } from "@/stores/accountContext";
import BaseButton from "@/components/base/BaseButton.vue";
import BaseSectionHeader from "@/components/base/BaseSectionHeader.vue";
import BaseCard from "@/components/base/BaseCard.vue";
import BaseBanner from "@/components/base/BaseBanner.vue";
import BaseSkeleton from "@/components/base/BaseSkeleton.vue";

////////////////////////////////////////////////////////////////////////
//
const router = useRouter();
const ctx = useAccountContextStore();

const {
  budgets,
  fillupFor,
  unallocated,
  budgetNames,
  recentTransactions: recentTx,
  allocationsByTx: allocsByTx,
  summary,
  loading,
  error,
} = useOverview();

function openBudget(id: string) {
  router.push({ name: "budget-detail", params: { id } });
}

function openTransaction(id: string) {
  router.push({ name: "transaction-detail", params: { id } });
}
</script>

<template>
  <AppShell>
    <div class="space-y-5 py-2">
      <!-- Balance strip -->
      <section v-if="ctx.activeBankAccount" class="grid grid-cols-3 gap-2">
        <BaseCard padded>
          <BaseSectionHeader title="Posted" as="div" class="mb-0.5" />
          <MoneyAmount
            :amount="ctx.activeBankAccount.postedBalance"
            size="md"
          />
        </BaseCard>
        <BaseCard padded>
          <BaseSectionHeader title="Available" as="div" class="mb-0.5" />
          <MoneyAmount
            :amount="ctx.activeBankAccount.availableBalance"
            size="md"
          />
        </BaseCard>
        <BaseCard padded>
          <BaseSectionHeader title="Free" as="div" class="mb-0.5" />
          <MoneyAmount
            v-if="unallocated"
            :amount="unallocated.balance"
            size="md"
          />
          <span v-else class="font-mono text-amount text-fg-subtle">—</span>
        </BaseCard>
      </section>

      <!-- Funding summary banner -->
      <BaseBanner v-if="summary && !summary.total.isZero()" tone="info">
        Funded automatically:
        <MoneyAmount :amount="summary.total" size="sm" class="font-medium" />
        <template v-if="summary.schedules[0]?.nextDate">
          on
          {{ formatLocalDate(summary.schedules[0].nextDate, "month-day") }}
        </template>
        <template v-if="summary.schedules.length > 1">
          across {{ summary.schedules.length }} schedules
        </template>
      </BaseBanner>

      <!-- Loading skeleton -->
      <template v-if="loading">
        <div class="space-y-2">
          <BaseSkeleton v-for="i in 4" :key="i" class="h-16" />
        </div>
      </template>

      <!-- Error -->
      <BaseBanner v-else-if="error" tone="danger">
        {{ error }}
      </BaseBanner>

      <template v-else>
        <!-- Budgets section -->
        <section v-if="budgets.length > 0">
          <div class="mb-2 flex items-center justify-between">
            <BaseSectionHeader title="Budgets" />
            <BaseButton
              variant="link"
              size="sm"
              @click="router.push({ name: 'budgets' })"
            >
              See all
              <IconChevronRight class="size-icon-xs" />
            </BaseButton>
          </div>
          <BaseCard>
            <ul>
              <li
                v-for="b in budgets"
                class="group cursor-pointer border-b border-border-subtle last:border-b-0 hover:bg-surface-sunken"
                :key="b.id"
                @click="openBudget(b.id)"
              >
                <div class="px-card-x py-card-y">
                  <div class="mb-1.5 flex items-baseline justify-between gap-2">
                    <div class="flex min-w-0 items-center gap-1.5">
                      <IconTarget
                        v-if="b.budgetType === 'G'"
                        class="size-icon-xs flex-none text-icon-muted"
                      />
                      <IconRepeat
                        v-else-if="b.budgetType === 'R'"
                        class="size-icon-xs flex-none text-icon-muted"
                      />
                      <IconBucket
                        v-else-if="b.budgetType === 'C'"
                        class="size-icon-xs flex-none text-icon-muted"
                      />
                      <span
                        class="min-w-0 truncate text-body font-medium text-fg"
                        >{{ b.name }}</span
                      >
                    </div>
                    <MoneyAmount
                      :amount="b.balance"
                      size="sm"
                      class="flex-none"
                    />
                  </div>
                  <ProgressBar
                    :value="budgetProgress(b)"
                    :tone="progressTone(budgetStatus(b))"
                    size="sm"
                    class="mb-1.5"
                  />
                  <div class="flex items-center justify-between gap-2">
                    <span
                      v-if="
                        b.nextFunding &&
                        (b.budgetType === 'G' || b.budgetType === 'C')
                      "
                      class="truncate text-meta text-fg-muted"
                    >
                      <MoneyAmount
                        :amount="b.nextFunding.amount"
                        size="sm"
                      />/event
                    </span>
                    <span v-else class="flex-1" />
                    <StatusChip
                      v-if="budgetStatus(b) !== 'progress'"
                      :status="budgetStatus(b)"
                      class="flex-none"
                    />
                  </div>
                </div>
                <FillUpBand v-if="fillupFor(b)" :budget="fillupFor(b)!" />
              </li>
            </ul>
          </BaseCard>
        </section>

        <!-- Recent transactions -->
        <section v-if="recentTx.length > 0">
          <div class="mb-2 flex items-center justify-between">
            <BaseSectionHeader title="Recent transactions" />
            <BaseButton
              variant="link"
              size="sm"
              @click="router.push({ name: 'transactions' })"
            >
              See all
              <IconChevronRight class="size-icon-xs" />
            </BaseButton>
          </div>
          <div class="space-y-2">
            <TransactionRow
              v-for="tx in recentTx"
              :key="tx.id"
              :transaction="tx"
              :allocations="allocsByTx.get(tx.id)"
              :budget-names="budgetNames"
              :unallocated-budget-id="ctx.unallocatedBudgetId"
              @select="openTransaction"
            />
          </div>
        </section>

        <!-- Empty state -->
        <div
          v-if="budgets.length === 0 && recentTx.length === 0 && !ctx.loading"
          class="py-10 text-center text-body-sm text-fg-subtle"
        >
          No budgets or transactions yet.
          <BaseButton
            variant="link"
            class="mt-2"
            @click="router.push({ name: 'budget-create' })"
          >
            Create your first budget
          </BaseButton>
        </div>
      </template>
    </div>
  </AppShell>
</template>
