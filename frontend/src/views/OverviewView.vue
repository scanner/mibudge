<script setup lang="ts">
//
// OverviewView — account health at a glance.
//
// Shows the active account's posted/available/unallocated balances,
// top non-archived budgets with progress bars, and recent transactions
// with allocation info rendered by TransactionRow.
//

// 3rd party imports
//
import { IconChevronRight } from "@tabler/icons-vue";
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";

// app imports
//
import AppShell from "@/components/layout/AppShell.vue";
import MoneyAmount from "@/components/shared/MoneyAmount.vue";
import ProgressBar from "@/components/shared/ProgressBar.vue";
import TransactionRow from "@/components/transactions/TransactionRow.vue";
import { listAllocations } from "@/api/allocations";
import { listBudgets } from "@/api/budgets";
import { listTransactions } from "@/api/transactions";
import { useAccountContextStore } from "@/stores/accountContext";
import { useBudgetsStore } from "@/stores/budgets";
import type { Budget, Transaction, TransactionAllocation } from "@/types/api";

////////////////////////////////////////////////////////////////////////
//
const router = useRouter();
const ctx = useAccountContextStore();
const budgetsStore = useBudgetsStore();

const budgets = ref<Budget[]>([]);
const recentTx = ref<Transaction[]>([]);
const allocsByTx = ref(new Map<string, TransactionAllocation[]>());
const loading = ref(false);
const error = ref<string | null>(null);

////////////////////////////////////////////////////////////////////////
//
const unallocated = computed(() => {
  const id = ctx.unallocatedBudgetId;
  if (!id) return null;
  return budgetsStore.byId(id);
});

const budgetNames = computed(() => {
  const map = new Map<string, string>();
  for (const b of budgetsStore.all) {
    map.set(b.id, b.name);
  }
  return map;
});

////////////////////////////////////////////////////////////////////////
//
// Progress percentage for a budget (0–100).  Returns null when there
// is no meaningful target to compare against.
//
function progressPct(b: Budget): number | null {
  const bal = Number.parseFloat(b.balance);
  if (b.budget_type === "G" || b.budget_type === "C") {
    const target = b.target_balance ? Number.parseFloat(b.target_balance) : null;
    if (!target || target <= 0) return null;
    return Math.min(100, (bal / target) * 100);
  }
  if (b.budget_type === "R") {
    const funding = b.funding_amount ? Number.parseFloat(b.funding_amount) : null;
    if (!funding || funding <= 0) return null;
    return Math.min(100, (bal / funding) * 100);
  }
  return null;
}

function progressTone(b: Budget): "mint" | "ocean" | "amber" | "coral" {
  const pct = progressPct(b);
  if (pct === null) return "ocean";
  if (b.budget_type === "G" || b.budget_type === "C") {
    if (pct >= 100) return "mint";
    if (pct >= 50) return "ocean";
    return "amber";
  }
  if (pct >= 80) return "mint";
  if (pct >= 40) return "ocean";
  if (pct >= 20) return "amber";
  return "coral";
}

////////////////////////////////////////////////////////////////////////
//
async function load() {
  const accountId = ctx.activeBankAccountId;
  if (!accountId) return;
  loading.value = true;
  error.value = null;
  try {
    const [budgetsPage, txPage] = await Promise.all([
      listBudgets({ bank_account: accountId, archived: false, ordering: "name" }),
      listTransactions({
        bank_account: accountId,
        ordering: "-transaction_date,-created_at",
      }),
    ]);

    for (const b of budgetsPage.results) budgetsStore.upsert(b);

    const unallocId = ctx.unallocatedBudgetId;
    budgets.value = budgetsPage.results
      .filter((b) => b.budget_type !== "A" && b.id !== unallocId)
      .slice(0, 6);

    const top5 = txPage.results.slice(0, 5);
    recentTx.value = top5;

    // Fetch allocations for each of the 5 transactions in parallel so
    // TransactionRow can show budget names and unallocated state.
    if (top5.length > 0) {
      const allocPages = await Promise.all(
        top5.map((tx) => listAllocations({ transaction: tx.id })),
      );
      const map = new Map<string, TransactionAllocation[]>();
      for (let i = 0; i < top5.length; i++) {
        map.set(top5[i].id, allocPages[i].results);
      }
      allocsByTx.value = map;
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Failed to load overview.";
  } finally {
    loading.value = false;
  }
}

watch(() => ctx.activeBankAccountId, load, { immediate: true });

onMounted(() => {
  // Ensure the unallocated budget is in the store for the balance tile
  // in case load() hasn't resolved yet on first render.
  const id = ctx.unallocatedBudgetId;
  if (id && !budgetsStore.byId(id)) budgetsStore.fetchOne(id);
});
</script>

<template>
  <AppShell>
    <div class="space-y-5 py-2">
      <!-- Balance strip -->
      <section v-if="ctx.activeBankAccount" class="grid grid-cols-3 gap-2">
        <div class="rounded-card border border-neutral-200 bg-white px-3 py-3">
          <div class="mb-0.5 text-[10px] font-semibold uppercase tracking-wider text-neutral-500">
            Posted
          </div>
          <MoneyAmount
            :amount="ctx.activeBankAccount.posted_balance"
            :currency="ctx.activeBankAccount.posted_balance_currency"
            size="md"
          />
        </div>
        <div class="rounded-card border border-neutral-200 bg-white px-3 py-3">
          <div class="mb-0.5 text-[10px] font-semibold uppercase tracking-wider text-neutral-500">
            Available
          </div>
          <MoneyAmount
            :amount="ctx.activeBankAccount.available_balance"
            :currency="ctx.activeBankAccount.available_balance_currency"
            size="md"
          />
        </div>
        <div class="rounded-card border border-neutral-200 bg-white px-3 py-3">
          <div class="mb-0.5 text-[10px] font-semibold uppercase tracking-wider text-neutral-500">
            Free
          </div>
          <MoneyAmount
            v-if="unallocated"
            :amount="unallocated.balance"
            :currency="unallocated.balance_currency"
            size="md"
          />
          <span v-else class="font-mono text-[15px] font-medium text-neutral-400">—</span>
        </div>
      </section>

      <!-- Loading skeleton -->
      <template v-if="loading">
        <div class="space-y-2">
          <div v-for="i in 4" :key="i" class="h-16 animate-pulse rounded-card bg-neutral-100" />
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
            <h2 class="text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
              Budgets
            </h2>
            <button
              type="button"
              class="flex items-center gap-0.5 text-[11px] font-medium text-ocean-600 hover:text-ocean-700"
              @click="router.push('/budgets/')"
            >
              See all
              <IconChevronRight class="h-3.5 w-3.5" />
            </button>
          </div>
          <div class="overflow-hidden rounded-card border border-neutral-200 bg-white">
            <ul class="divide-y divide-neutral-100">
              <li
                v-for="b in budgets"
                :key="b.id"
                class="cursor-pointer px-4 py-3 hover:bg-neutral-50"
                @click="router.push(`/budgets/${b.id}/`)"
              >
                <div class="mb-1.5 flex items-baseline justify-between gap-2">
                  <span class="min-w-0 truncate text-[14px] font-medium text-neutral-900">
                    {{ b.name }}
                  </span>
                  <MoneyAmount
                    :amount="b.balance"
                    :currency="b.balance_currency"
                    size="sm"
                    class="flex-none"
                  />
                </div>
                <ProgressBar
                  v-if="progressPct(b) !== null"
                  :value="progressPct(b)!"
                  :tone="progressTone(b)"
                  :height="3"
                />
              </li>
            </ul>
          </div>
        </section>

        <!-- Recent transactions -->
        <section v-if="recentTx.length > 0">
          <div class="mb-2 flex items-center justify-between">
            <h2 class="text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
              Recent transactions
            </h2>
            <button
              type="button"
              class="flex items-center gap-0.5 text-[11px] font-medium text-ocean-600 hover:text-ocean-700"
              @click="router.push('/transactions/')"
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
            @click="router.push('/budgets/create/')"
          >
            Create your first budget
          </button>
        </div>
      </template>
    </div>
  </AppShell>
</template>
