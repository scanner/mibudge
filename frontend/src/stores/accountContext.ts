//
// Account-context store — the "which bank account am I looking at?"
// global.  Every list view that filters by account reads
// `activeBankAccountId` from here and passes it as the `bank_account`
// query param.
//
// Initialisation order (UI_SPEC §6):
//   1. Read the cached UUID from localStorage (may be stale).
//   2. Fetch the user's bank accounts.
//   3. Choose the active account: user.default_bank_account (GAP-1
//      fallback: first account returned) → cached UUID if still valid
//      → first account.
//   4. Persist the chosen UUID back to localStorage.
//
// Downstream: the unallocated-budget UUID is derived from the active
// account and exposed separately so TopBar and allocation-tagging code
// can reach it without re-reading the whole BankAccount object.
//

// 3rd party imports
//
import { defineStore } from "pinia";
import { computed, ref } from "vue";

// app imports
//
import { listBankAccounts } from "@/api/bankAccounts";
import { getCurrentUser } from "@/api/users";
import type { BankAccount } from "@/types/api";

////////////////////////////////////////////////////////////////////////
//
const STORAGE_KEY = "mibudge.activeBankAccountId";

////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////
//
export const useAccountContextStore = defineStore("accountContext", () => {
  ////////////////////////////////////////////////////////////////////
  //
  const accounts = ref<BankAccount[]>([]);
  const activeBankAccountId = ref<string | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);

  ////////////////////////////////////////////////////////////////////
  //
  const activeBankAccount = computed<BankAccount | null>(() => {
    const id = activeBankAccountId.value;
    if (!id) return null;
    return accounts.value.find((a) => a.id === id) ?? null;
  });

  ////////////////////////////////////////////////////////////////////
  //
  const unallocatedBudgetId = computed<string | null>(
    () => activeBankAccount.value?.unallocated_budget ?? null,
  );

  ////////////////////////////////////////////////////////////////////
  //
  function setActive(id: string | null) {
    activeBankAccountId.value = id;
    if (id) {
      window.localStorage.setItem(STORAGE_KEY, id);
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  }

  ////////////////////////////////////////////////////////////////////
  //
  // Load accounts and pick the active one.  Safe to call on every
  // app boot — runs once per session unless `force` is true.
  //
  async function init(force = false): Promise<void> {
    if (!force && accounts.value.length > 0) return;
    loading.value = true;
    error.value = null;
    try {
      // Fetch accounts first; the user fetch is advisory (only needed
      // for `default_bank_account` once GAP-1 is closed).
      const [accountsPage, user] = await Promise.all([
        listBankAccounts(),
        getCurrentUser().catch(() => null),
      ]);
      accounts.value = accountsPage.results;

      const cached = window.localStorage.getItem(STORAGE_KEY);
      const validIds = new Set(accounts.value.map((a) => a.id));

      // Preference order: server-side default → cached → first account.
      let chosen: string | null = null;
      if (user?.default_bank_account && validIds.has(user.default_bank_account)) {
        chosen = user.default_bank_account;
      } else if (cached && validIds.has(cached)) {
        chosen = cached;
      } else if (accounts.value.length > 0) {
        chosen = accounts.value[0].id;
      }
      setActive(chosen);
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err);
    } finally {
      loading.value = false;
    }
  }

  ////////////////////////////////////////////////////////////////////
  //
  // Refresh just the active-account record (e.g. after a rename or
  // balance-changing event).  Leaves the active ID untouched.
  //
  async function refresh(): Promise<void> {
    const page = await listBankAccounts();
    accounts.value = page.results;
  }

  ////////////////////////////////////////////////////////////////////
  //
  function clear() {
    accounts.value = [];
    setActive(null);
  }

  return {
    accounts,
    activeBankAccountId,
    activeBankAccount,
    unallocatedBudgetId,
    loading,
    error,
    init,
    refresh,
    setActive,
    clear,
  };
});
