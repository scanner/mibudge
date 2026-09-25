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
import MoneyAmount from "@/components/shared/MoneyAmount.vue";
import ProgressBar from "@/components/shared/ProgressBar.vue";
import StatusChip from "@/components/shared/StatusChip.vue";
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
        <div class="rounded-card border border-neutral-200 bg-white px-3 py-3">
          <div
            class="mb-0.5 text-[10px] font-semibold uppercase tracking-wider text-neutral-500"
          >
            Posted
          </div>
          <MoneyAmount
            :amount="ctx.activeBankAccount.postedBalance"
            size="md"
          />
        </div>
        <div class="rounded-card border border-neutral-200 bg-white px-3 py-3">
          <div
            class="mb-0.5 text-[10px] font-semibold uppercase tracking-wider text-neutral-500"
          >
            Available
          </div>
          <MoneyAmount
            :amount="ctx.activeBankAccount.availableBalance"
            size="md"
          />
        </div>
        <div class="rounded-card border border-neutral-200 bg-white px-3 py-3">
          <div
            class="mb-0.5 text-[10px] font-semibold uppercase tracking-wider text-neutral-500"
          >
            Free
          </div>
          <MoneyAmount
            v-if="unallocated"
            :amount="unallocated.balance"
            size="md"
          />
          <span
            v-else
            class="font-mono text-[15px] font-medium text-neutral-400"
            >—</span
          >
        </div>
      </section>

      <!-- Funding summary banner -->
      <div
        v-if="summary && !summary.total.isZero()"
        class="rounded-card border border-ocean-200 bg-ocean-50 px-4 py-2.5 text-[13px] text-ocean-700"
      >
        Funded automatically:
        <MoneyAmount :amount="summary.total" size="sm" class="font-medium" />
        <template v-if="summary.schedules[0]?.nextDate">
          on
          {{
            formatLocalDate(summary.schedules[0].nextDate, {
              month: "short",
              day: "numeric",
            })
          }}
        </template>
        <template v-if="summary.schedules.length > 1">
          across {{ summary.schedules.length }} schedules
        </template>
      </div>

      <!-- Loading skeleton -->
      <template v-if="loading">
        <div class="space-y-2">
          <div
            v-for="i in 4"
            :key="i"
            class="h-16 animate-pulse rounded-card bg-neutral-100"
          />
        </div>
      </template>

      <!-- Error -->
      <div
        v-else-if="error"
        class="rounded-card bg-coral-50 px-4 py-3 text-sm text-coral-600"
        role="alert"
      >
        {{ error }}
      </div>

      <template v-else>
        <!-- Budgets section -->
        <section v-if="budgets.length > 0">
          <div class="mb-2 flex items-center justify-between">
            <h2
              class="text-[11px] font-semibold uppercase tracking-wider text-neutral-500"
            >
              Budgets
            </h2>
            <button
              type="button"
              class="flex items-center gap-0.5 text-[11px] font-medium text-ocean-600 hover:text-ocean-700"
              @click="router.push({ name: 'budgets' })"
            >
              See all
              <IconChevronRight class="h-3.5 w-3.5" />
            </button>
          </div>
          <div
            class="overflow-hidden rounded-card border border-neutral-200 bg-white"
          >
            <ul class="divide-y divide-neutral-100">
              <li
                v-for="b in budgets"
                :key="b.id"
                class="group cursor-pointer hover:bg-neutral-50"
                @click="openBudget(b.id)"
              >
                <div class="px-4 py-3">
                  <div class="mb-1.5 flex items-baseline justify-between gap-2">
                    <div class="flex min-w-0 items-center gap-1.5">
                      <IconTarget
                        v-if="b.budgetType === 'G'"
                        class="h-3.5 w-3.5 flex-none text-neutral-400"
                      />
                      <IconRepeat
                        v-else-if="b.budgetType === 'R'"
                        class="h-3.5 w-3.5 flex-none text-neutral-400"
                      />
                      <IconBucket
                        v-else-if="b.budgetType === 'C'"
                        class="h-3.5 w-3.5 flex-none text-neutral-400"
                      />
                      <span
                        class="min-w-0 truncate text-[14px] font-medium text-neutral-900"
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
                    :height="3"
                    class="mb-1.5"
                  />
                  <div class="flex items-center justify-between gap-2">
                    <span
                      v-if="
                        b.nextFunding &&
                        (b.budgetType === 'G' || b.budgetType === 'C')
                      "
                      class="truncate text-[12px] text-secondary"
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
          </div>
        </section>

        <!-- Recent transactions -->
        <section v-if="recentTx.length > 0">
          <div class="mb-2 flex items-center justify-between">
            <h2
              class="text-[11px] font-semibold uppercase tracking-wider text-neutral-500"
            >
              Recent transactions
            </h2>
            <button
              type="button"
              class="flex items-center gap-0.5 text-[11px] font-medium text-ocean-600 hover:text-ocean-700"
              @click="router.push({ name: 'transactions' })"
            >
              See all
              <IconChevronRight class="h-3.5 w-3.5" />
            </button>
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
          class="py-10 text-center text-sm text-neutral-400"
        >
          No budgets or transactions yet.
          <button
            type="button"
            class="mt-2 block w-full text-ocean-600 hover:text-ocean-700"
            @click="router.push({ name: 'budget-create' })"
          >
            Create your first budget
          </button>
        </div>
      </template>
    </div>
  </AppShell>
</template>
