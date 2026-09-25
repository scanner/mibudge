//
// `useTransactionDetail`: one transaction with its allocations, the
// autosaved description and memo, split editing, attachments, and
// previous / next navigation.  Feature composable (transactions).
//
// Everything follows the `id` getter.  Autosaves are keyed by id: a
// pending save is cancelled when the id changes or the view unmounts,
// so text typed for one transaction is never written to another.  A
// cleared memo is sent as `null`, which clears it on the server.
//
// A split updates the allocation cache for the transaction list and
// refetches the account's budgets, so balances everywhere (including
// the top bar's Unallocated) are current.
//

// 3rd party imports
//
import { computed, ref, shallowRef, watch } from "vue";

// app imports
//
import { api } from "@/api";
import { describeError } from "@/api/errors";
import { useDebouncedAutosave } from "@/composables/useDebouncedAutosave";
import { useResource } from "@/composables/useResource";
import type { Allocation } from "@/models/allocation";
import {
  allocationCoverage,
  allocationFromDto,
  assignedAllocations,
  splitsOf,
} from "@/models/allocation";
import type { Transaction } from "@/models/transaction";
import { transactionFromDto, transactionToUpdateDto } from "@/models/transaction";
import { useAccountContextStore } from "@/stores/accountContext";
import { useAllocationsStore } from "@/stores/allocations";
import { useBudgetsStore } from "@/stores/budgets";
import { useTransactionNavStore } from "@/stores/transactionNav";

////////////////////////////////////////////////////////////////////////
//
export type AttachmentField = "image" | "document";

async function allocationsOf(transactionId: string): Promise<Allocation[]> {
  const first = await api.allocations.list({ transaction: transactionId });
  return (await api.pages.all(first)).map(allocationFromDto);
}

////////////////////////////////////////////////////////////////////////
//
export function useTransactionDetail(id: () => string) {
  const ctx = useAccountContextStore();
  const budgets = useBudgetsStore();
  const allocationsStore = useAllocationsStore();
  const nav = useTransactionNavStore();

  ////////////////////////////////////////////////////////////////////
  //
  const transaction = shallowRef<Transaction | null>(null);
  const allocations = shallowRef<Allocation[]>([]);
  const description = ref("");
  const memo = ref("");
  const attachmentError = ref<string | null>(null);

  const resource = useResource(
    id,
    async (txId: string) => {
      const [tx, allocs] = await Promise.all([
        api.transactions.get(txId).then(transactionFromDto),
        allocationsOf(txId),
      ]);
      // The split editor lists the account's budgets.
      await budgets.refreshAccount(tx.bankAccountId).catch(() => undefined);
      return { tx, allocs };
    },
    { errorMessage: "Failed to load transaction." },
  );

  watch(resource.data, (data) => {
    transaction.value = data?.tx ?? null;
    allocations.value = data?.allocs ?? [];
    description.value = data?.tx.description ?? "";
    memo.value = data?.tx.memo ?? "";
    attachmentError.value = null;
  });

  // Apply a server answer only while it is still the transaction shown.
  //
  function applyIfCurrent(txId: string, updated: Transaction): void {
    if (txId === id() && transaction.value?.id === txId) transaction.value = updated;
  }

  ////////////////////////////////////////////////////////////////////
  //
  // Autosave (800ms after the last keystroke).  A failed save restores
  // the saved text.
  //
  const descriptionSave = useDebouncedAutosave(id, async (txId: string, value: string) => {
    if (value === transaction.value?.description) return;
    try {
      const dto = await api.transactions.update(
        txId,
        transactionToUpdateDto({ description: value }),
      );
      applyIfCurrent(txId, transactionFromDto(dto));
    } catch (err) {
      if (txId === id()) description.value = transaction.value?.description ?? "";
      throw err;
    }
  });

  const memoSave = useDebouncedAutosave(id, async (txId: string, value: string) => {
    if ((value || null) === (transaction.value?.memo ?? null)) return;
    try {
      const dto = await api.transactions.update(txId, transactionToUpdateDto({ memo: value }));
      applyIfCurrent(txId, transactionFromDto(dto));
    } catch (err) {
      if (txId === id()) memo.value = transaction.value?.memo ?? "";
      throw err;
    }
  });

  ////////////////////////////////////////////////////////////////////
  //
  const unallocatedBudgetId = computed(() => ctx.unallocatedBudgetId);
  const visibleAllocations = computed(() =>
    assignedAllocations(allocations.value, unallocatedBudgetId.value),
  );
  const coverage = computed(() =>
    transaction.value
      ? allocationCoverage(transaction.value.amount, visibleAllocations.value)
      : null,
  );
  const initialSplits = computed(() =>
    visibleAllocations.value
      .filter((a) => a.budgetId)
      .map((a) => ({ budgetId: a.budgetId!, amount: a.amount.abs().toDecimalString() })),
  );
  const accountBudgets = computed(() => budgets.forAccount(transaction.value?.bankAccountId));

  function budgetName(budgetId: string | null): string {
    if (!budgetId) return "Unallocated";
    return budgets.byId(budgetId)?.name ?? "Budget";
  }

  ////////////////////////////////////////////////////////////////////
  //
  async function applySplits(splits: Record<string, string>): Promise<void> {
    const tx = transaction.value;
    if (!tx) return;
    try {
      const updated = (await api.transactions.split(tx.id, splits)).map(allocationFromDto);
      if (tx.id === id()) allocations.value = updated;
      allocationsStore.setForTransaction(tx.bankAccountId, tx.id, updated);
      await budgets.refreshAccount(tx.bankAccountId).catch(() => undefined);
    } catch {
      if (tx.id === id()) allocations.value = await allocationsOf(tx.id).catch(() => []);
    }
  }

  async function updateAllocation(allocationId: string, amount: string): Promise<void> {
    const alloc = visibleAllocations.value.find((a) => a.id === allocationId);
    if (!alloc?.budgetId) return;
    const splits = splitsOf(visibleAllocations.value);
    splits[alloc.budgetId] = amount.replace(/^-/, "");
    await applySplits(splits);
  }

  async function removeAllocation(allocationId: string): Promise<void> {
    const alloc = visibleAllocations.value.find((a) => a.id === allocationId);
    if (!alloc?.budgetId) return;
    const splits = splitsOf(visibleAllocations.value);
    delete splits[alloc.budgetId];
    await applySplits(splits);
  }

  ////////////////////////////////////////////////////////////////////
  //
  async function uploadAttachment(field: AttachmentField, file: File): Promise<void> {
    const txId = id();
    attachmentError.value = null;
    try {
      const dto = await api.transactions.uploadAttachment(txId, field, file);
      applyIfCurrent(txId, transactionFromDto(dto));
    } catch (err) {
      if (txId !== id()) return;
      const what = field === "image" ? "photo" : "document";
      attachmentError.value = `Couldn't attach the ${what}: ${describeError(err, "upload failed.")}`;
    }
  }

  ////////////////////////////////////////////////////////////////////
  //
  const prevId = computed(() => nav.prevId(id()));
  const nextId = computed(() => nav.nextId(id()));

  return {
    transaction,
    loading: resource.loading,
    error: resource.error,
    description,
    memo,
    onDescriptionInput: () => descriptionSave.schedule(description.value),
    onDescriptionBlur: () => descriptionSave.flush(),
    onMemoInput: () => memoSave.schedule(memo.value),
    onMemoBlur: () => memoSave.flush(),
    unallocatedBudgetId,
    visibleAllocations,
    coverage,
    initialSplits,
    accountBudgets,
    budgetName,
    applySplits,
    updateAllocation,
    removeAllocation,
    attachmentError,
    uploadAttachment,
    prevId,
    nextId,
  };
}
