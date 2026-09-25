//
// Allocation cache: every allocation of a bank account, indexed by
// transaction.  Store layer.
//
// The transaction list needs each row's allocations; the API has no
// endpoint that embeds them in the transaction list, so the account's
// allocations are fetched once and reused across visits.  A split
// replaces the affected transaction's entries in place
// (`setForTransaction`), so returning to the list needs no refetch.
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

  ////////////////////////////////////////////////////////////////////
  //
  function indexFor(accountId: string): Map<string, Allocation[]> | null {
    return byAccount.value.get(accountId) ?? null;
  }

  ////////////////////////////////////////////////////////////////////
  //
  // The account's allocation index, fetched on first use.  Concurrent
  // callers share one fetch.
  //
  function loadForAccount(accountId: string, force = false): Promise<Map<string, Allocation[]>> {
    const cached = byAccount.value.get(accountId);
    if (cached && !force) return Promise.resolve(cached);
    const pending = inFlight.get(accountId);
    if (pending && !force) return pending;

    // A load superseded by `invalidate()` or a forced reload does not
    // write its (older) result.
    //
    const load: Promise<Map<string, Allocation[]>> = fetchIndex(accountId)
      .then((index) => {
        if (inFlight.get(accountId) === load) byAccount.value.set(accountId, index);
        return index;
      })
      .finally(() => {
        if (inFlight.get(accountId) === load) inFlight.delete(accountId);
      });
    inFlight.set(accountId, load);
    return load;
  }

  ////////////////////////////////////////////////////////////////////
  //
  // Replace one transaction's allocations in its account's index (a
  // no-op when that index is not loaded).
  //
  function setForTransaction(
    accountId: string,
    transactionId: string,
    allocations: Allocation[],
  ): void {
    const index = byAccount.value.get(accountId);
    if (index) index.set(transactionId, allocations);
  }

  ////////////////////////////////////////////////////////////////////
  //
  function invalidate(accountId?: string): void {
    if (accountId) {
      byAccount.value.delete(accountId);
      inFlight.delete(accountId);
    } else {
      byAccount.value.clear();
      inFlight.clear();
    }
  }

  function reset(): void {
    invalidate();
  }

  // The backing map is returned so Pinia treats it as state.
  return { byAccount, indexFor, loadForAccount, setForTransaction, invalidate, reset };
});
