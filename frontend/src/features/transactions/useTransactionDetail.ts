//
// `useTransactionDetail`: one transaction with its allocations, the
// autosaved description and memo, split editing, attachments, and
// previous / next navigation.  Feature composable (transactions).
//
// Everything follows the `id` getter.  Autosaves are keyed by id: a
// pending save is flushed to the transaction it was typed for when the
// id changes or the view unmounts, so text typed for one transaction is
// saved there and never written to another.  A
// cleared memo is sent as `null`, which clears it on the server.
//
// The allocations are the transaction's own (embedded by the server).
// A split replaces them and refetches the account's budgets, so
// balances everywhere (including the top bar's Unallocated) are
// current.
//
// The shown transaction refreshes in the background when the bank
// account's transactions may have changed (`stores/invalidation.ts`),
// so a pending transaction that posted or a co-owner's split shows.
// The description and memo keep text typed here and not yet saved, and
// an answer is dropped when this page saved, split or uploaded while it
// was in flight.  A transaction the refresh finds gone (a bank sync
// replaces pending transactions) shows the error a missing link does.
//
// A failed autosave, split or upload leaves a message naming what was
// not saved, with the server's reason (`descriptionError`,
// `memoError`, `splitError`, `attachmentError`); each clears when the
// transaction changes.
//

// 3rd party imports
//
import { computed, ref, shallowRef, watch } from "vue";

// app imports
//
import { api } from "@/api";
import { ApiError, describeError } from "@/api/errors";
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
import {
  transactionFromDto,
  transactionToUpdateDto,
} from "@/models/transaction";
import { useBankAccountsStore } from "@/stores/bankAccounts";
import { useBudgetsStore } from "@/stores/budgets";
import { accountInterest, useInvalidationStore } from "@/stores/invalidation";
import { useTransactionNavStore } from "@/stores/transactionNav";

////////////////////////////////////////////////////////////////////////
//
export type AttachmentField = "image" | "document";

// Autosave failures read "Couldn't save the memo: <reason>".
const SAVE_FAILED = { errorMessage: "save failed." };

////////////////////////////////////////////////////////////////////////
//
export function useTransactionDetail(id: () => string) {
  const bankAccounts = useBankAccountsStore();
  const budgets = useBudgetsStore();
  const nav = useTransactionNavStore();

  ////////////////////////////////////////////////////////////////////
  //
  const transaction = shallowRef<Transaction | null>(null);
  const description = ref("");
  const memo = ref("");
  const attachmentError = ref<string | null>(null);
  const splitError = ref<string | null>(null);
  // Set when a background refresh finds the transaction gone.
  const goneError = ref<string | null>(null);

  const resource = useResource(
    id,
    async (txId: string) => {
      const tx = transactionFromDto(await api.transactions.get(txId));
      // The split editor lists the account's budgets; a failed refresh
      // leaves the cached ones.
      await budgets.refreshAccount(tx.bankAccountId).catch(() => undefined);
      return tx;
    },
    { errorMessage: "Failed to load transaction." },
  );

  watch(resource.data, (tx) => {
    transaction.value = tx ?? null;
    description.value = tx?.description ?? "";
    memo.value = tx?.memo ?? "";
    attachmentError.value = null;
    splitError.value = null;
    goneError.value = null;
  });

  // Apply a text or attachment save's answer only while it is still the
  // transaction shown.  The shown allocations are kept: only a split
  // sets them, and a save answered before a split lands carries the
  // older ones.
  //
  // Every write this page makes to the transaction runs through
  // `tracked`, so a background refresh can tell it raced one.
  //
  let writes = 0;
  let writesInFlight = 0;

  async function tracked<R>(request: () => Promise<R>): Promise<R> {
    writes++;
    writesInFlight++;
    try {
      return await request();
    } finally {
      writesInFlight--;
      writes++;
    }
  }

  function applyIfCurrent(txId: string, updated: Transaction): void {
    const current = transaction.value;
    if (txId === id() && current?.id === txId)
      transaction.value = { ...updated, allocations: current.allocations };
  }

  // Replace the shown transaction's allocations, if it is still `txId`.
  //
  function setAllocationsIfCurrent(
    txId: string,
    allocations: Allocation[],
  ): void {
    const current = transaction.value;
    if (txId === id() && current?.id === txId)
      transaction.value = { ...current, allocations };
  }

  ////////////////////////////////////////////////////////////////////
  //
  // Autosave (800ms after the last keystroke).  A failed save restores
  // the saved text and says why.
  //
  const descriptionSave = useDebouncedAutosave(
    id,
    async (txId: string, value: string) => {
      if (value === transaction.value?.description) return;
      try {
        const dto = await tracked(() =>
          api.transactions.update(
            txId,
            transactionToUpdateDto({ description: value }),
          ),
        );
        applyIfCurrent(txId, transactionFromDto(dto));
      } catch (err) {
        if (txId === id())
          description.value = transaction.value?.description ?? "";
        throw err;
      }
    },
    SAVE_FAILED,
  );

  const memoSave = useDebouncedAutosave(
    id,
    async (txId: string, value: string) => {
      if ((value || null) === (transaction.value?.memo ?? null)) return;
      try {
        const dto = await tracked(() =>
          api.transactions.update(
            txId,
            transactionToUpdateDto({ memo: value }),
          ),
        );
        applyIfCurrent(txId, transactionFromDto(dto));
      } catch (err) {
        if (txId === id()) memo.value = transaction.value?.memo ?? "";
        throw err;
      }
    },
    SAVE_FAILED,
  );

  const descriptionError = computed(() =>
    descriptionSave.error.value
      ? `Couldn't save the description: ${descriptionSave.error.value}`
      : null,
  );
  const memoError = computed(() =>
    memoSave.error.value
      ? `Couldn't save the memo: ${memoSave.error.value}`
      : null,
  );

  ////////////////////////////////////////////////////////////////////
  //
  // The transaction's own account, which need not be the active one
  // (e.g. a link to another account's transaction).
  const account = computed(() =>
    bankAccounts.byId(transaction.value?.bankAccountId),
  );
  const accountName = computed(() => account.value?.name ?? "");
  const unallocatedBudgetId = computed(
    () => account.value?.unallocatedBudgetId ?? null,
  );
  const visibleAllocations = computed(() =>
    assignedAllocations(
      transaction.value?.allocations ?? [],
      unallocatedBudgetId.value,
    ),
  );
  const coverage = computed(() =>
    transaction.value
      ? allocationCoverage(transaction.value.amount, visibleAllocations.value)
      : null,
  );
  const initialSplits = computed(() =>
    visibleAllocations.value
      .filter((a) => a.budgetId)
      .map((a) => ({
        budgetId: a.budgetId!,
        amount: a.amount.abs().toDecimalString(),
      })),
  );
  const accountBudgets = computed(() =>
    budgets.forAccount(transaction.value?.bankAccountId),
  );

  function budgetName(budgetId: string | null): string {
    if (!budgetId) return "Unallocated";
    return budgets.byId(budgetId)?.name ?? "Budget";
  }

  ////////////////////////////////////////////////////////////////////
  //
  // A failed split says why and reloads the transaction's allocations,
  // so the list shows what the server has (or keeps what it showed, if
  // that reload fails too).  After a split, a failed budget refresh
  // leaves the cached balances.
  //
  async function applySplits(splits: Record<string, string>): Promise<void> {
    const tx = transaction.value;
    if (!tx) return;
    splitError.value = null;
    let updated: Allocation[];
    try {
      updated = (
        await tracked(() => api.transactions.split(tx.id, splits))
      ).map(allocationFromDto);
    } catch (err) {
      if (tx.id !== id()) return;
      splitError.value = `Couldn't save the split: ${describeError(err, "save failed.")}`;
      const current = await api.transactions.get(tx.id).catch(() => null);
      if (current)
        setAllocationsIfCurrent(tx.id, transactionFromDto(current).allocations);
      return;
    }
    setAllocationsIfCurrent(tx.id, updated);
    await budgets.refreshAccount(tx.bankAccountId).catch(() => undefined);
  }

  async function updateAllocation(
    allocationId: string,
    amount: string,
  ): Promise<void> {
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
  async function uploadAttachment(
    field: AttachmentField,
    file: File,
  ): Promise<void> {
    const txId = id();
    attachmentError.value = null;
    try {
      const dto = await tracked(() =>
        api.transactions.uploadAttachment(txId, field, file),
      );
      applyIfCurrent(txId, transactionFromDto(dto));
    } catch (err) {
      if (txId !== id()) return;
      const what = field === "image" ? "photo" : "document";
      attachmentError.value = `Couldn't attach the ${what}: ${describeError(err, "upload failed.")}`;
    }
  }

  ////////////////////////////////////////////////////////////////////
  //
  // Background refresh.  Skipped while a write is in flight (its answer
  // is newer), and dropped if one started meanwhile.
  //
  async function refresh(): Promise<void> {
    const txId = id();
    const shown = transaction.value;
    if (!shown || shown.id !== txId || writesInFlight > 0) return;
    const started = writes;
    let fresh: Transaction;
    try {
      fresh = transactionFromDto(await api.transactions.get(txId));
    } catch (err) {
      if (
        err instanceof ApiError &&
        err.status === 404 &&
        txId === id() &&
        transaction.value?.id === txId
      ) {
        descriptionSave.cancel();
        memoSave.cancel();
        transaction.value = null;
        goneError.value = describeError(err, "Failed to load transaction.");
      }
      return;
    }
    const current = transaction.value;
    if (txId !== id() || current?.id !== txId || writes !== started) return;
    if (
      !descriptionSave.pending.value &&
      description.value === current.description
    )
      description.value = fresh.description;
    if (!memoSave.pending.value && memo.value === (current.memo ?? ""))
      memo.value = fresh.memo ?? "";
    transaction.value = fresh;
  }

  const invalidation = useInvalidationStore();
  invalidation.onInvalidate(
    () => accountInterest(transaction.value?.bankAccountId, ["transactions"]),
    refresh,
  );
  invalidation.onInvalidate(
    () => accountInterest(transaction.value?.bankAccountId, ["budgets"]),
    () => budgets.refreshAccount(transaction.value!.bankAccountId),
  );

  ////////////////////////////////////////////////////////////////////
  //
  const prevId = computed(() => nav.prevId(id()));
  const nextId = computed(() => nav.nextId(id()));

  return {
    transaction,
    loading: resource.loading,
    error: computed(() => goneError.value ?? resource.error.value),
    description,
    memo,
    onDescriptionInput: () => descriptionSave.schedule(description.value),
    onDescriptionBlur: () => descriptionSave.flush(),
    onMemoInput: () => memoSave.schedule(memo.value),
    onMemoBlur: () => memoSave.flush(),
    descriptionError,
    memoError,
    accountName,
    unallocatedBudgetId,
    visibleAllocations,
    coverage,
    initialSplits,
    accountBudgets,
    budgetName,
    applySplits,
    updateAllocation,
    removeAllocation,
    splitError,
    attachmentError,
    uploadAttachment,
    prevId,
    nextId,
  };
}
