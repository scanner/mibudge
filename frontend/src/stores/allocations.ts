//
// Allocation cache: every allocation of a bank account, indexed by
// transaction.  Store layer.
//
// The transaction list needs each row's allocations; the API has no
// endpoint that embeds them in the transaction list, so the account's
// allocations are fetched as one index.  The list refetches it on every
// visit (`loadForAccount(id, true)`) because other writers change it: a
// sync gives pending transactions new ids, and a co-owner can re-split.
// The previous index stays readable until the refetch lands, so rows
// keep their budgets on screen meanwhile.
//
// A split in this tab replaces the transaction's entries in place
// (`setForTransaction`).  A refetch already in flight may have read the
// server before that split, so the split is re-applied to its result.
//

// 3rd party imports
//
import { defineStore } from "pinia";
import { ref } from "vue";

// app imports
//
import { api } from "@/api";
import type { Allocation } from "@/models/allocation";
import { allocationFromDto, indexByTransaction } from "@/models/allocation";

////////////////////////////////////////////////////////////////////////
//
async function fetchIndex(accountId: string): Promise<Map<string, Allocation[]>> {
  const first = await api.allocations.list({ bank_account: accountId });
  return indexByTransaction((await api.pages.all(first)).map(allocationFromDto));
}

////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////
//
export const useAllocationsStore = defineStore("allocations", () => {
  // account id → (transaction id → allocations)
  const byAccount = ref(new Map<string, Map<string, Allocation[]>>());
  const inFlight = new Map<string, Promise<Map<string, Allocation[]>>>();
  // account id → splits saved while that account's load is in flight.
  const splitsDuringLoad = new Map<string, Map<string, Allocation[]>>();

  ////////////////////////////////////////////////////////////////////
  //
  function indexFor(accountId: string): Map<string, Allocation[]> | null {
    return byAccount.value.get(accountId) ?? null;
  }

  ////////////////////////////////////////////////////////////////////
  //
  // The account's allocation index: the cached one unless `force` is
  // set or none is cached.  Concurrent unforced callers share one
  // fetch; a forced call starts a new one.
  //
  function loadForAccount(accountId: string, force = false): Promise<Map<string, Allocation[]>> {
    const cached = byAccount.value.get(accountId);
    if (cached && !force) return Promise.resolve(cached);
    const pending = inFlight.get(accountId);
    if (pending && !force) return pending;

    // A load superseded by `invalidate()` or a newer forced load does
    // not write its (older) result.
    //
    const splits = new Map<string, Allocation[]>();
    const load: Promise<Map<string, Allocation[]>> = fetchIndex(accountId)
      .then((index) => {
        if (inFlight.get(accountId) !== load) return index;
        for (const [txId, allocations] of splits) index.set(txId, allocations);
        byAccount.value.set(accountId, index);
        return index;
      })
      .finally(() => {
        if (inFlight.get(accountId) === load) {
          inFlight.delete(accountId);
          splitsDuringLoad.delete(accountId);
        }
      });
    inFlight.set(accountId, load);
    splitsDuringLoad.set(accountId, splits);
    return load;
  }

  ////////////////////////////////////////////////////////////////////
  //
  // Replace one transaction's allocations in its account's index, and
  // in the result of a load now in flight.  A no-op for an account
  // with neither.
  //
  function setForTransaction(
    accountId: string,
    transactionId: string,
    allocations: Allocation[],
  ): void {
    byAccount.value.get(accountId)?.set(transactionId, allocations);
    splitsDuringLoad.get(accountId)?.set(transactionId, allocations);
  }

  ////////////////////////////////////////////////////////////////////
  //
  function invalidate(accountId?: string): void {
    if (accountId) {
      byAccount.value.delete(accountId);
      inFlight.delete(accountId);
      splitsDuringLoad.delete(accountId);
    } else {
      byAccount.value.clear();
      inFlight.clear();
      splitsDuringLoad.clear();
    }
  }

  function reset(): void {
    invalidate();
  }

  // The backing map is returned so Pinia treats it as state.
  return { byAccount, indexFor, loadForAccount, setForTransaction, invalidate, reset };
});
