<script setup lang="ts">
//
// BudgetDetailView — full detail screen for a single budget.
// (UI_SPEC §4.3)
//
// Sections:
//  1. Hero block (BudgetDetailHero)
//  2. "Move money" CTA → inline internal transaction form
//  3. Configuration rows (read-only display, editing via BudgetForm sheet)
//  4. Pause / archive action row
//  5. Transaction list
//

// 3rd party imports
//
import {
  IconArchive,
  IconArrowsRightLeft,
  IconCalendar,
  IconClock,
  IconCoin,
  IconPencil,
  IconPlayerPause,
  IconRefresh,
  IconSearch,
  IconTarget,
  IconX,
} from "@tabler/icons-vue";

import { Fzf } from "fzf";
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

// app imports
//
import BudgetDetailHero from "@/components/budgets/BudgetDetailHero.vue";
import BudgetForm from "@/components/budgets/BudgetForm.vue";
import AppShell from "@/components/layout/AppShell.vue";
import ConfirmSheet from "@/components/shared/ConfirmSheet.vue";
import MoneyAmount from "@/components/shared/MoneyAmount.vue";
import InternalTransactionRow from "@/components/transactions/InternalTransactionRow.vue";
import TransactionRow from "@/components/transactions/TransactionRow.vue";
import { listAllocations } from "@/api/allocations";
import { archiveBudget, getBudget, updateBudget } from "@/api/budgets";
import { listBudgets } from "@/api/budgets";
import { createInternalTransaction, listInternalTransactions } from "@/api/internalTransactions";
import { getTransaction, splitTransaction } from "@/api/transactions";
import { fetchAllPages } from "@/api/util";
import { useAccountContextStore } from "@/stores/accountContext";
import { useAuthStore } from "@/stores/auth";
import { useBudgetsStore } from "@/stores/budgets";
import { parseLocalDate } from "@/utils/budget";
import { formatDateHeader, todayDateStr, txDateStr } from "@/utils/dates";
import { rruleHuman } from "@/utils/rrule";
import type { Budget, InternalTransaction, Transaction, TransactionAllocation } from "@/types/api";

////////////////////////////////////////////////////////////////////////
//
const props = defineProps<{ id: string }>();
const router = useRouter();
const ctx = useAccountContextStore();
const auth = useAuthStore();
const store = useBudgetsStore();

const budget = ref<Budget | null>(null);
const fillupBudget = ref<Budget | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);

const showEditSheet = ref(false);
const showArchiveConfirm = ref(false);
const showMoveMoneyForm = ref(false);

////////////////////////////////////////////////////////////////////////
//
const accountName = computed(() => ctx.activeBankAccount?.name);
const isUnallocated = computed(() => budget.value?.id === ctx.unallocatedBudgetId);

////////////////////////////////////////////////////////////////////////
//
async function load() {
  loading.value = true;
  error.value = null;
  try {
    const b = await getBudget(props.id);
    budget.value = b;
    store.upsert(b);
    // Fetch fill-up budget if present
    if (b.with_fillup_goal && b.fillup_goal) {
      fillupBudget.value = await getBudget(b.fillup_goal);
    }
  } catch {
    error.value = "Failed to load budget.";
  } finally {
    loading.value = false;
  }
}

onMounted(load);

////////////////////////////////////////////////////////////////////////
//
// Transactions associated with this budget via allocations.
//
const budgetTransactions = ref<Transaction[]>([]);
const budgetAllocsByTx = ref(new Map<string, TransactionAllocation[]>());
const txLoading = ref(false);
const searchOpen = ref(false);
const searchQuery = ref("");
const searchResults = ref<Transaction[] | null>(null);
let fzfDebounce: ReturnType<typeof setTimeout> | null = null;
const searchInput = ref<HTMLInputElement | null>(null);

////////////////////////////////////////////////////////////////////////
//
// Internal transaction toggle state.
//
const showInternalTxs = ref(false);
const budgetInternalTxs = ref<InternalTransaction[]>([]);
const internalTxsLoading = ref(false);

const budgetNames = computed(() => {
  const map = new Map<string, string>();
  for (const b of store.all) map.set(b.id, b.name);
  return map;
});

////////////////////////////////////////////////////////////////////////
//
// Date-grouped display — mixes Transaction and InternalTransaction rows,
// sorted by effective date within each group.
//
type DisplayRow = { kind: "tx"; tx: Transaction } | { kind: "itx"; itx: InternalTransaction };

interface DateGroup {
  date: string;
  label: string;
  rows: DisplayRow[];
}

const displayTransactions = computed(() => {
  const tz = auth.timezone;
  const today = todayDateStr(tz);
  const map = new Map<string, DateGroup>();

  for (const tx of searchResults.value ?? budgetTransactions.value) {
    const date = txDateStr(tx.transaction_date, tz);
    let group = map.get(date);
    if (!group) {
      group = { date, label: formatDateHeader(date, today, tz), rows: [] };
      map.set(date, group);
    }
    group.rows.push({ kind: "tx", tx });
  }

  if (showInternalTxs.value) {
    for (const itx of budgetInternalTxs.value) {
      const date = txDateStr(itx.effective_date, tz);
      let group = map.get(date);
      if (!group) {
        group = { date, label: formatDateHeader(date, today, tz), rows: [] };
        map.set(date, group);
      }
      group.rows.push({ kind: "itx", itx });
    }
    // Sort rows within each group by date desc.
    for (const group of map.values()) {
      group.rows.sort((a, b) => {
        const aDate = a.kind === "tx" ? a.tx.transaction_date : a.itx.effective_date;
        const bDate = b.kind === "tx" ? b.tx.transaction_date : b.itx.effective_date;
        return aDate > bDate ? -1 : aDate < bDate ? 1 : 0;
      });
    }
  }

  return Array.from(map.values()).sort((a, b) => (a.date > b.date ? -1 : 1));
});

async function loadBudgetTransactions() {
  txLoading.value = true;
  try {
    const firstPage = await listAllocations({ budget: props.id });
    const allAllocs = await fetchAllPages(firstPage);

    // Index allocations by transaction and fetch the unique transactions.
    const allocMap = new Map<string, TransactionAllocation[]>();
    const txIds = new Set<string>();
    for (const a of allAllocs) {
      txIds.add(a.transaction);
      const list = allocMap.get(a.transaction) ?? [];
      list.push(a);
      allocMap.set(a.transaction, list);
    }

    const txPromises = Array.from(txIds).map((id) => getTransaction(id));
    const txs = await Promise.all(txPromises);

    // The budget filter above gives us only one allocation per transaction.
    // For split transactions (where that single allocation doesn't cover the
    // full amount), fetch all allocations so the row can display every budget.
    const splitFetches = txs
      .filter((tx) => {
        const allocs = allocMap.get(tx.id);
        if (!allocs || allocs.length !== 1) return false;
        return Math.abs(parseFloat(allocs[0].amount)) !== Math.abs(parseFloat(tx.amount));
      })
      .map(async (tx) => {
        const page = await listAllocations({ transaction: tx.id });
        allocMap.set(tx.id, await fetchAllPages(page));
      });
    await Promise.all(splitFetches);

    budgetAllocsByTx.value = allocMap;

    txs.sort((a, b) =>
      a.transaction_date !== b.transaction_date
        ? a.transaction_date > b.transaction_date
          ? -1
          : 1
        : a.created_at > b.created_at
          ? -1
          : 1,
    );
    budgetTransactions.value = txs;
  } catch {
    // Non-fatal — the budget detail still shows, transactions section just stays empty.
  } finally {
    txLoading.value = false;
  }
}

onMounted(loadBudgetTransactions);

async function loadBudgetInternalTransactions() {
  internalTxsLoading.value = true;
  try {
    const firstPage = await listInternalTransactions({ budget: props.id });
    budgetInternalTxs.value = await fetchAllPages(firstPage);
  } catch {
    // Non-fatal.
  } finally {
    internalTxsLoading.value = false;
  }
}

async function toggleInternalTxs() {
  showInternalTxs.value = !showInternalTxs.value;
  if (showInternalTxs.value && budgetInternalTxs.value.length === 0) {
    await loadBudgetInternalTransactions();
  }
}

////////////////////////////////////////////////////////////////////////
//
// Transaction search — client-side fzf only (all transactions loaded in memory).
//
function onSearchInput() {
  const q = searchQuery.value.trim();
  if (!q) {
    searchResults.value = null;
    return;
  }
  if (fzfDebounce) clearTimeout(fzfDebounce);
  fzfDebounce = setTimeout(() => {
    const fzf = new Fzf(budgetTransactions.value, {
      selector: (tx: Transaction) => `${tx.party ?? ""} ${tx.description} ${tx.raw_description}`,
      casing: "case-insensitive",
      fuzzy: false,
    });
    searchResults.value = fzf.find(q).map((r) => r.item);
  }, 150);
}

function toggleSearch() {
  searchOpen.value = !searchOpen.value;
  if (!searchOpen.value) {
    searchQuery.value = "";
    searchResults.value = null;
  } else {
    nextTick(() => searchInput.value?.focus());
  }
}

function onSearchKeydown(e: KeyboardEvent) {
  if (e.key === "f" && (e.metaKey || e.ctrlKey)) {
    e.preventDefault();
    if (!searchOpen.value) searchOpen.value = true;
    nextTick(() => searchInput.value?.focus());
  } else if (e.key === "Escape" && searchOpen.value) {
    toggleSearch();
  }
}

onMounted(() => window.addEventListener("keydown", onSearchKeydown));
onBeforeUnmount(() => window.removeEventListener("keydown", onSearchKeydown));

async function onRemoveTransaction(transactionId: string) {
  const allocs = budgetAllocsByTx.value.get(transactionId);
  if (!allocs) return;

  const allocForThisBudget = allocs.find((a) => a.budget === props.id);
  if (!allocForThisBudget) return;

  try {
    // Build a splits dict from all current allocations, minus this budget.
    const allTxAllocs = await listAllocations({ transaction: transactionId });
    const splits: Record<string, string> = {};
    for (const a of allTxAllocs.results) {
      if (a.budget && a.budget !== props.id) {
        splits[a.budget] = Math.abs(parseFloat(a.amount)).toString();
      }
    }
    await splitTransaction(transactionId, splits);

    // Remove from local lists (both the source array and any active search results).
    budgetTransactions.value = budgetTransactions.value.filter((tx) => tx.id !== transactionId);
    if (searchResults.value) {
      searchResults.value = searchResults.value.filter((tx) => tx.id !== transactionId);
    }
    budgetAllocsByTx.value.delete(transactionId);

    // Refresh budget to update balance.
    const updated = await getBudget(props.id);
    budget.value = updated;
    store.upsert(updated);
    // Refresh all budgets so TopBar stays current.
    if (ctx.activeBankAccountId) {
      await store.fetchList({ bank_account: ctx.activeBankAccountId });
    }
  } catch {
    // Reload on error.
    await loadBudgetTransactions();
  }
}

////////////////////////////////////////////////////////////////////////
//
async function togglePause() {
  if (!budget.value) return;
  try {
    const updated = await updateBudget(budget.value.id, { paused: !budget.value.paused });
    budget.value = updated;
    store.upsert(updated);
  } catch {
    error.value = "Failed to update budget.";
  }
}

async function confirmArchive() {
  if (!budget.value) return;
  try {
    const updated = await archiveBudget(budget.value.id);
    store.upsert(updated);
    router.push("/budgets/");
  } catch {
    error.value = "Failed to archive budget.";
    showArchiveConfirm.value = false;
  }
}

function onSaved(updated: Budget) {
  budget.value = updated;
  store.upsert(updated);
  showEditSheet.value = false;
}

////////////////////////////////////////////////////////////////////////
//
// "Move money" internal transaction form state.
//
// One side is always this budget.  The user picks a direction
// (into or out of) and the other budget.
//
const otherBudgets = ref<Budget[]>([]);
const moveDirection = ref<"into" | "outof">("outof");
const moveTargetFillup = ref(false);
const moveOtherId = ref("");
const moveAmount = ref("");
const moveSaving = ref(false);
const moveError = ref<string | null>(null);
const moveAmountInput = ref<HTMLInputElement | null>(null);

const fillupParentNames = computed(() => {
  const map = new Map<string, string>();
  for (const b of otherBudgets.value) {
    if (b.fillup_goal) map.set(b.fillup_goal, b.name);
  }
  return map;
});

// When targeting the fill-up goal, exclude it from the "other budget" picker.
const movePickerBudgets = computed(() => {
  if (moveTargetFillup.value && fillupBudget.value) {
    return otherBudgets.value.filter((b) => b.id !== fillupBudget.value!.id);
  }
  return otherBudgets.value;
});

////////////////////////////////////////////////////////////////////////
//
// Next funding display — computed from the budget's next_funding field
// (or from fillupBudget.next_funding for RECURRING+with_fillup budgets).
//
interface NextFundingDisplay {
  date: Date;
  amount: string;
  amount_currency: string;
  daysAway: number;
  deferred: boolean;
  deferredReason: string | null; // human-readable explanation when deferred
  isFillup: boolean; // true when the event belongs to the fill-up goal
}

const nextFundingDisplay = computed((): NextFundingDisplay | null => {
  const b = budget.value;
  if (!b) return null;

  const today = parseLocalDate(todayDateStr(auth.timezone));

  // For RECURRING+with_fillup, the API returns null on the parent. We
  // display the fill-up goal's next_funding on the parent's detail page.
  const isRecurringWithFillup = b.budget_type === "R" && b.with_fillup_goal && !!b.fillup_goal;
  const nf = isRecurringWithFillup ? (fillupBudget.value?.next_funding ?? null) : b.next_funding;

  if (!nf) return null;

  const eventDate = parseLocalDate(nf.date);
  const msPerDay = 1000 * 60 * 60 * 24;
  const daysAway = Math.round((eventDate.getTime() - today.getTime()) / msPerDay);

  let deferredReason: string | null = null;
  if (nf.deferred) {
    const lpt = ctx.activeBankAccount?.last_posted_through;
    if (lpt) {
      const lptDate = parseLocalDate(lpt);
      deferredReason = `Account data current through ${lptDate.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}`;
    } else {
      deferredReason = "No import data recorded yet";
    }
  }

  return {
    date: eventDate,
    amount: nf.amount,
    amount_currency: nf.amount_currency,
    daysAway,
    deferred: nf.deferred,
    deferredReason,
    isFillup: isRecurringWithFillup,
  };
});

function budgetPickerLabel(b: Budget): string {
  if (b.budget_type === "A") {
    const parent = fillupParentNames.value.get(b.id);
    return parent ? `${parent} (fill-up)` : `${b.name} (fill-up)`;
  }
  return b.name;
}

async function openMoveMoneyForm() {
  if (!ctx.activeBankAccountId) return;
  const page = await listBudgets({ bank_account: ctx.activeBankAccountId, archived: false });
  otherBudgets.value = page.results.filter((b) => b.id !== props.id);
  moveDirection.value = "into";
  moveTargetFillup.value = false;
  const unallocId = ctx.unallocatedBudgetId;
  const unalloc = unallocId ? otherBudgets.value.find((b) => b.id === unallocId) : null;
  moveOtherId.value = unalloc?.id ?? otherBudgets.value[0]?.id ?? "";
  moveAmount.value = "";
  moveError.value = null;
  showMoveMoneyForm.value = true;
  nextTick(() => moveAmountInput.value?.focus());
}

function setMoveTarget(toFillup: boolean) {
  moveTargetFillup.value = toFillup;
  // Reset the counterpart picker to its first valid option.
  const unallocId = ctx.unallocatedBudgetId;
  const pool =
    toFillup && fillupBudget.value
      ? otherBudgets.value.filter((b) => b.id !== fillupBudget.value!.id)
      : otherBudgets.value;
  const unalloc = unallocId ? pool.find((b) => b.id === unallocId) : null;
  moveOtherId.value = unalloc?.id ?? pool[0]?.id ?? "";
}

async function submitMove() {
  if (!moveOtherId.value || !moveAmount.value || !budget.value) return;
  moveSaving.value = true;
  moveError.value = null;

  const thisBudgetId =
    moveTargetFillup.value && fillupBudget.value ? fillupBudget.value.id : props.id;
  const srcId = moveDirection.value === "outof" ? thisBudgetId : moveOtherId.value;
  const dstId = moveDirection.value === "outof" ? moveOtherId.value : thisBudgetId;

  try {
    await createInternalTransaction({
      bank_account: budget.value.bank_account,
      src_budget: srcId,
      dst_budget: dstId,
      amount: moveAmount.value,
    });
    showMoveMoneyForm.value = false;
    await Promise.all([store.fetchOne(srcId), store.fetchOne(dstId)]);
    const updated = store.byId(props.id);
    if (updated) budget.value = updated;
    if (fillupBudget.value) {
      const updatedFillup = store.byId(fillupBudget.value.id);
      if (updatedFillup) fillupBudget.value = updatedFillup;
    }
  } catch {
    moveError.value = "Transfer failed. Check the amount and try again.";
  } finally {
    moveSaving.value = false;
  }
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
          @click="openMoveMoneyForm"
        >
          <IconArrowsRightLeft class="mt-0.5 h-5 w-5 flex-none text-ocean-400" />
          <div>
            <div class="text-[15px] font-medium text-ocean-600">Move money</div>
            <div class="text-xs text-secondary">Transfer to or from another budget</div>
          </div>
        </button>

        <!-- Configuration section -->
        <section
          v-if="!isUnallocated"
          class="overflow-hidden rounded-card border border-neutral-200 bg-white"
        >
          <h2
            class="border-b border-neutral-100 px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-neutral-500"
          >
            Configuration
          </h2>

          <!-- Goal-specific rows -->
          <template v-if="budget.budget_type === 'G'">
            <div class="flex items-center gap-3 border-b border-neutral-100 px-4 py-3">
              <IconTarget class="h-4 w-4 flex-none text-neutral-400" />
              <span class="flex-1 text-sm text-neutral-700">Target amount</span>
              <MoneyAmount
                v-if="budget.target_balance"
                :amount="budget.target_balance"
                :currency="budget.target_balance_currency"
                size="md"
              />
              <span v-else class="text-sm text-secondary">—</span>
            </div>
            <div class="flex items-center gap-3 border-b border-neutral-100 px-4 py-3">
              <IconCalendar class="h-4 w-4 flex-none text-neutral-400" />
              <span class="flex-1 text-sm text-neutral-700">Target date</span>
              <span class="text-sm text-secondary">
                {{
                  budget.target_date
                    ? parseLocalDate(budget.target_date).toLocaleDateString(undefined, {
                        month: "short",
                        day: "numeric",
                        year: "numeric",
                      })
                    : "—"
                }}
              </span>
            </div>
            <div class="flex items-center gap-3 px-4 py-3">
              <IconClock class="h-4 w-4 flex-none text-neutral-400" />
              <span class="flex-1 text-sm text-neutral-700">Funding schedule</span>
              <span class="text-right text-sm text-secondary">
                {{ budget.funding_schedule ? rruleHuman(budget.funding_schedule) : "—" }}
              </span>
            </div>
          </template>

          <!-- Capped-specific rows -->
          <template v-else-if="budget.budget_type === 'C'">
            <div class="flex items-center gap-3 border-b border-neutral-100 px-4 py-3">
              <IconTarget class="h-4 w-4 flex-none text-neutral-400" />
              <span class="flex-1 text-sm text-neutral-700">Cap</span>
              <MoneyAmount
                v-if="budget.target_balance"
                :amount="budget.target_balance"
                :currency="budget.target_balance_currency"
                size="md"
              />
              <span v-else class="text-sm text-secondary">—</span>
            </div>
            <div class="flex items-center gap-3 border-b border-neutral-100 px-4 py-3">
              <IconCoin class="h-4 w-4 flex-none text-neutral-400" />
              <span class="flex-1 text-sm text-neutral-700">Amount per event</span>
              <MoneyAmount
                v-if="budget.funding_amount"
                :amount="budget.funding_amount"
                :currency="budget.funding_amount_currency"
                size="md"
              />
              <span v-else class="text-sm text-secondary">—</span>
            </div>
            <div class="flex items-center gap-3 px-4 py-3">
              <IconClock class="h-4 w-4 flex-none text-neutral-400" />
              <span class="flex-1 text-sm text-neutral-700">Funding schedule</span>
              <span class="text-right text-sm text-secondary">
                {{ budget.funding_schedule ? rruleHuman(budget.funding_schedule) : "—" }}
              </span>
            </div>
          </template>

          <!-- Recurring-specific rows -->
          <template v-else>
            <div class="flex items-center gap-3 border-b border-neutral-100 px-4 py-3">
              <IconRefresh class="h-4 w-4 flex-none text-neutral-400" />
              <span class="flex-1 text-sm text-neutral-700">Refresh cycle</span>
              <span class="text-right text-sm text-secondary">
                {{ budget.recurrence_schedule ? rruleHuman(budget.recurrence_schedule) : "—" }}
              </span>
            </div>
            <div class="flex items-center gap-3 border-b border-neutral-100 px-4 py-3">
              <IconClock class="h-4 w-4 flex-none text-neutral-400" />
              <span class="flex-1 text-sm text-neutral-700">Funding schedule</span>
              <span class="text-right text-sm text-secondary">
                {{ budget.funding_schedule ? rruleHuman(budget.funding_schedule) : "—" }}
              </span>
            </div>
            <div class="flex items-center gap-3 border-b border-neutral-100 px-4 py-3">
              <IconTarget class="h-4 w-4 flex-none text-neutral-400" />
              <span class="flex-1 text-sm text-neutral-700">Target amount</span>
              <MoneyAmount
                v-if="budget.target_balance"
                :amount="budget.target_balance"
                :currency="budget.target_balance_currency"
                size="md"
              />
              <span v-else class="text-sm text-secondary">—</span>
            </div>
            <div class="flex items-center justify-between gap-3 px-4 py-3">
              <span class="text-sm text-neutral-700">Fill-up goal</span>
              <span
                class="rounded-full px-2 py-0.5 text-xs font-medium"
                :class="
                  budget.with_fillup_goal
                    ? 'bg-mint-50 text-mint-600'
                    : 'bg-neutral-100 text-neutral-500'
                "
              >
                {{ budget.with_fillup_goal ? "Enabled" : "Disabled" }}
              </span>
            </div>
          </template>

          <!-- Next funding row — shown for any budget that has an upcoming event -->
          <div
            v-if="nextFundingDisplay"
            class="flex items-start gap-3 border-t border-neutral-100 px-4 py-3"
          >
            <IconCalendar class="mt-0.5 h-4 w-4 flex-none text-neutral-400" />
            <div class="flex-1">
              <span class="text-sm text-neutral-700"> Next fill-up deposit </span>
              <div v-if="nextFundingDisplay.deferred" class="mt-0.5 text-xs text-amber-600">
                Delayed — {{ nextFundingDisplay.deferredReason }}
              </div>
            </div>
            <div class="text-right">
              <MoneyAmount
                :amount="nextFundingDisplay.amount"
                :currency="nextFundingDisplay.amount_currency"
                size="md"
              />
              <div class="mt-0.5 text-xs text-secondary">
                {{
                  nextFundingDisplay.date.toLocaleDateString(undefined, {
                    month: "short",
                    day: "numeric",
                    year: "numeric",
                  })
                }}
                <span v-if="nextFundingDisplay.daysAway === 0">(today)</span>
                <span v-else-if="nextFundingDisplay.daysAway === 1">(tomorrow)</span>
                <span v-else-if="nextFundingDisplay.daysAway > 0">
                  (in {{ nextFundingDisplay.daysAway }} days)
                </span>
                <span v-else>({{ Math.abs(nextFundingDisplay.daysAway) }} days ago)</span>
              </div>
            </div>
          </div>
        </section>

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
        <section class="mt-2">
          <div class="mb-2 flex items-center justify-between">
            <h2 class="text-[11px] font-semibold uppercase tracking-wider text-secondary">
              Transactions
            </h2>
            <div class="flex items-center gap-1">
              <button
                type="button"
                class="flex h-7 w-7 items-center justify-center rounded-full transition-colors"
                :class="
                  showInternalTxs
                    ? 'bg-ocean-400 text-white hover:bg-ocean-600'
                    : 'text-neutral-500 hover:bg-neutral-100'
                "
                :aria-label="showInternalTxs ? 'Hide transfers' : 'Show transfers'"
                :title="showInternalTxs ? 'Hide transfers' : 'Show transfers'"
                @click="toggleInternalTxs"
              >
                <IconArrowsRightLeft class="h-4 w-4" />
              </button>
              <button
                type="button"
                class="flex h-7 w-7 items-center justify-center rounded-full text-neutral-500 hover:bg-neutral-100"
                aria-label="Search transactions"
                @click="toggleSearch"
              >
                <IconSearch v-if="!searchOpen" class="h-4 w-4" />
                <IconX v-else class="h-4 w-4" />
              </button>
            </div>
          </div>

          <Transition
            enter-active-class="transition-all duration-200 ease-out"
            enter-from-class="max-h-0 opacity-0"
            enter-to-class="max-h-12 opacity-100"
            leave-active-class="transition-all duration-150 ease-in"
            leave-from-class="max-h-12 opacity-100"
            leave-to-class="max-h-0 opacity-0"
          >
            <div v-if="searchOpen" class="-mx-4 overflow-hidden px-4 pb-3">
              <input
                ref="searchInput"
                v-model="searchQuery"
                type="text"
                placeholder="Search transactions…"
                class="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-900 outline-none transition-colors placeholder:text-neutral-400 focus:border-ocean-400 focus:ring-1 focus:ring-ocean-400"
                @input="onSearchInput"
              />
            </div>
          </Transition>

          <div v-if="txLoading" class="space-y-2">
            <div v-for="i in 3" :key="i" class="h-16 animate-pulse rounded-card bg-neutral-100" />
          </div>

          <div v-else-if="displayTransactions.length > 0" class="space-y-4">
            <section v-for="group in displayTransactions" :key="group.date">
              <h3
                class="sticky top-0 z-10 -mx-4 bg-neutral-50/95 px-4 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-secondary backdrop-blur-sm"
              >
                {{ group.label }}
              </h3>
              <div class="space-y-2">
                <template
                  v-for="row in group.rows"
                  :key="row.kind + (row.kind === 'tx' ? row.tx.id : row.itx.id)"
                >
                  <TransactionRow
                    v-if="row.kind === 'tx'"
                    :transaction="row.tx"
                    :allocations="budgetAllocsByTx.get(row.tx.id)"
                    :budget-names="budgetNames"
                    :unallocated-budget-id="ctx.unallocatedBudgetId"
                    removable
                    @remove="onRemoveTransaction"
                  />
                  <InternalTransactionRow
                    v-else
                    :internal-transaction="row.itx"
                    :budget-names="budgetNames"
                    :relative-to-budget-id="id"
                  />
                </template>
              </div>
            </section>
          </div>

          <p v-else class="py-4 text-center text-sm text-secondary">
            {{
              searchQuery
                ? "No matching transactions."
                : "No transactions assigned to this budget yet."
            }}
          </p>
        </section>

        <!-- Inline error banner -->
        <p v-if="error" class="rounded-subcard bg-coral-50 px-4 py-2 text-sm text-coral-600">
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
    <Teleport to="body">
      <Transition name="slide-up">
        <div
          v-if="showEditSheet && budget"
          class="fixed inset-0 z-40 overflow-y-auto bg-neutral-50"
          @keydown.esc="showEditSheet = false"
        >
          <div class="mx-auto max-w-lg px-4 pb-8 pt-4">
            <div class="mb-4 flex items-center justify-between">
              <h2 class="text-[18px] font-medium text-neutral-900">Edit budget</h2>
            </div>
            <BudgetForm
              mode="edit"
              :budget="budget"
              @saved="onSaved"
              @cancel="showEditSheet = false"
            />
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- Move money sheet -->
    <Teleport to="body">
      <Transition name="fade">
        <div
          v-if="showMoveMoneyForm"
          class="fixed inset-0 z-40 flex items-end justify-center md:items-center"
          @keydown.esc="showMoveMoneyForm = false"
        >
          <div class="absolute inset-0 bg-neutral-900/40" @click="showMoveMoneyForm = false" />
          <div
            class="relative w-full rounded-t-2xl bg-white p-5 shadow-xl md:w-[480px] md:rounded-card"
          >
            <h2 class="mb-4 text-[18px] font-medium text-neutral-900">Move money</h2>

            <div class="space-y-3">
              <div>
                <label class="mb-1 block text-[13px] font-medium text-neutral-700">Direction</label>
                <div class="flex rounded-subcard border border-neutral-200">
                  <button
                    type="button"
                    class="flex-1 rounded-l-subcard py-2.5 text-sm font-medium transition-colors"
                    :class="
                      moveDirection === 'outof'
                        ? 'bg-ocean-400 text-white'
                        : 'text-secondary hover:bg-neutral-50'
                    "
                    @click="moveDirection = 'outof'"
                  >
                    Out of this budget
                  </button>
                  <button
                    type="button"
                    class="flex-1 rounded-r-subcard py-2.5 text-sm font-medium transition-colors"
                    :class="
                      moveDirection === 'into'
                        ? 'bg-ocean-400 text-white'
                        : 'text-secondary hover:bg-neutral-50'
                    "
                    @click="moveDirection = 'into'"
                  >
                    Into this budget
                  </button>
                </div>
              </div>

              <div v-if="fillupBudget">
                <label class="mb-1 block text-[13px] font-medium text-neutral-700"
                  >This budget</label
                >
                <div class="flex rounded-subcard border border-neutral-200">
                  <button
                    type="button"
                    class="flex-1 rounded-l-subcard py-2.5 text-sm font-medium transition-colors"
                    :class="
                      !moveTargetFillup
                        ? 'bg-ocean-400 text-white'
                        : 'text-secondary hover:bg-neutral-50'
                    "
                    @click="setMoveTarget(false)"
                  >
                    {{ budget?.name }}
                  </button>
                  <button
                    type="button"
                    class="flex-1 rounded-r-subcard py-2.5 text-sm font-medium transition-colors"
                    :class="
                      moveTargetFillup
                        ? 'bg-ocean-400 text-white'
                        : 'text-secondary hover:bg-neutral-50'
                    "
                    @click="setMoveTarget(true)"
                  >
                    {{ fillupBudget.name }} (fill-up)
                  </button>
                </div>
              </div>

              <div>
                <label class="mb-1 block text-[13px] font-medium text-neutral-700">
                  {{ moveDirection === "outof" ? "To" : "From" }}
                </label>
                <select
                  v-model="moveOtherId"
                  class="w-full rounded-subcard border border-neutral-200 px-3 py-2.5 text-sm text-neutral-900"
                >
                  <option v-for="b in movePickerBudgets" :key="b.id" :value="b.id">
                    {{ budgetPickerLabel(b) }}
                  </option>
                </select>
              </div>

              <div>
                <label class="mb-1 block text-[13px] font-medium text-neutral-700">Amount</label>
                <input
                  ref="moveAmountInput"
                  v-model="moveAmount"
                  type="number"
                  min="0.01"
                  step="0.01"
                  placeholder="0.00"
                  class="w-full rounded-subcard border border-neutral-200 px-3 py-2.5 font-mono text-[15px] text-neutral-900 focus:border-ocean-400 focus:outline-none"
                  @keydown.enter="moveOtherId && moveAmount && !moveSaving && submitMove()"
                />
              </div>

              <p v-if="moveError" class="text-sm text-coral-600">{{ moveError }}</p>

              <div class="flex gap-2 pt-1">
                <button
                  type="button"
                  class="flex-1 rounded-full border border-neutral-200 py-3 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
                  @click="showMoveMoneyForm = false"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  :disabled="!moveOtherId || !moveAmount || moveSaving"
                  class="flex-1 rounded-full py-3 text-sm font-medium text-white transition-colors"
                  :class="
                    moveOtherId && moveAmount && !moveSaving
                      ? 'bg-ocean-400 hover:bg-ocean-600'
                      : 'cursor-not-allowed bg-neutral-300'
                  "
                  @click="submitMove"
                >
                  {{ moveSaving ? "Transferring…" : "Transfer" }}
                </button>
              </div>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </AppShell>
</template>

<style scoped>
.slide-up-enter-active,
.slide-up-leave-active {
  transition: transform 250ms ease-out;
}
.slide-up-enter-from,
.slide-up-leave-to {
  transform: translateY(100%);
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 120ms ease-out;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
