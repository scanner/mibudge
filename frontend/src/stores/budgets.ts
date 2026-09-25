//
// Budget entity cache.  Store layer.
//
// Caches budgets as models, keyed by id.  Views and composables read
// from here (`byId`, `forAccount`, `names`) and mutate through the
// actions, which update the cache from the server's answer -- so the
// top bar's Unallocated balance and every budget list stay current
// without callers copying results back by hand.
//
// `refreshAccount(accountId)` refetches an account's budgets after an
// operation that moves money between them on the server (splits,
// funding runs); `invalidate(ids)` drops entries so the next read
// refetches.
//

// 3rd party imports
//
import { defineStore } from "pinia";
import { computed, ref } from "vue";

// app imports
//
import { api } from "@/api";
import type { BudgetListQuery } from "@/api/dto";
import { describeError } from "@/api/errors";
import type { Budget, BudgetCreateInput, BudgetInput } from "@/models/budget";
import {
  budgetFromDto,
  budgetNameIndex,
  budgetToCreateDto,
  budgetToUpdateDto,
} from "@/models/budget";
import type { TransferInput } from "@/models/internalTransaction";
import { transferToCreateDto } from "@/models/internalTransaction";
import { createSessionGuard } from "@/stores/reset";

////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////
//
export const useBudgetsStore = defineStore("budgets", () => {
  ////////////////////////////////////////////////////////////////////
  //
  const cache = ref(new Map<string, Budget>());
  const loading = ref(false);
  const error = ref<string | null>(null);

  const all = computed(() => Array.from(cache.value.values()));
  const names = computed(() => budgetNameIndex(cache.value.values()));

  ////////////////////////////////////////////////////////////////////
  //
  function byId(id: string | null | undefined): Budget | null {
    if (!id) return null;
    return cache.value.get(id) ?? null;
  }

  function forAccount(accountId: string | null | undefined): Budget[] {
    if (!accountId) return [];
    return all.value.filter((b) => b.bankAccountId === accountId);
  }

  function upsert(budget: Budget): void {
    cache.value.set(budget.id, budget);
  }

  ////////////////////////////////////////////////////////////////////
  //
  // A request writes its answer to the cache only if no sign-out
  // (`reset()`) happened while it was in flight.
  //
  const guard = createSessionGuard();
  const whileCurrent = guard.whileCurrent;

  ////////////////////////////////////////////////////////////////////
  //
  async function fetchOne(id: string): Promise<Budget> {
    const put = whileCurrent(upsert);
    const budget = budgetFromDto(await api.budgets.get(id));
    put(budget);
    return budget;
  }

  ////////////////////////////////////////////////////////////////////
  //
  // Fetch every page of a filtered list and cache the results.
  //
  async function fetchList(query?: BudgetListQuery): Promise<Budget[]> {
    const put = whileCurrent(upsert);
    loading.value = true;
    error.value = null;
    try {
      const first = await api.budgets.list(query);
      const budgets = (await api.pages.all(first)).map(budgetFromDto);
      for (const b of budgets) put(b);
      return budgets;
    } catch (err) {
      error.value = describeError(err, "Failed to load budgets.");
      throw err;
    } finally {
      loading.value = false;
    }
  }

  function refreshAccount(accountId: string): Promise<Budget[]> {
    return fetchList({ bank_account: accountId });
  }

  ////////////////////////////////////////////////////////////////////
  //
  async function create(input: BudgetCreateInput): Promise<Budget> {
    const put = whileCurrent(upsert);
    const budget = budgetFromDto(await api.budgets.create(budgetToCreateDto(input)));
    put(budget);
    return budget;
  }

  async function update(id: string, input: BudgetInput): Promise<Budget> {
    const put = whileCurrent(upsert);
    const budget = budgetFromDto(await api.budgets.update(id, budgetToUpdateDto(input)));
    put(budget);
    return budget;
  }

  // Archiving moves the balance to Unallocated, so the account's
  // budgets are refetched; the archive succeeded, so a failed refetch
  // leaves the cached balances.
  //
  async function archive(id: string): Promise<Budget> {
    const started = guard.current();
    const budget = budgetFromDto(await api.budgets.archive(id));
    if (!guard.isCurrent(started)) return budget;
    upsert(budget);
    await refreshAccount(budget.bankAccountId).catch(() => undefined);
    return budget;
  }

  // Move money between two budgets, then refetch both.
  //
  async function transfer(input: TransferInput): Promise<void> {
    const started = guard.current();
    await api.internalTransactions.create(transferToCreateDto(input));
    if (!guard.isCurrent(started)) return;
    await Promise.all([fetchOne(input.srcBudgetId), fetchOne(input.dstBudgetId)]);
  }

  ////////////////////////////////////////////////////////////////////
  //
  // Drop cached budgets (all of them when no ids are given).
  //
  function invalidate(ids?: string[]): void {
    if (!ids) {
      cache.value.clear();
      return;
    }
    for (const id of ids) cache.value.delete(id);
  }

  function reset(): void {
    guard.bump();
    cache.value.clear();
    loading.value = false;
    error.value = null;
  }

  // The backing cache is returned so Pinia treats it as state.
  return {
    cache,
    all,
    names,
    loading,
    error,
    byId,
    forAccount,
    upsert,
    fetchOne,
    fetchList,
    refreshAccount,
    create,
    update,
    archive,
    transfer,
    invalidate,
    reset,
  };
});
