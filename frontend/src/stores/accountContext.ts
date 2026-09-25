//
// Account-context store: which bank account the user is looking at.
// Store layer.
//
// Every per-account view reads `activeBankAccountId` from here.  The
// choice is kept per browser tab in sessionStorage, so two tabs can
// look at different accounts.
//
// `init()` picks the active account:
//   1. the id stored for this tab, if it is still one of the user's
//      accounts;
//   2. else the user's `defaultBankAccountId`;
//   3. else the first account.
// It loads the account list through the bank-accounts cache and the
// user through the session store, whose `loadUser()` is shared with
// the cold-boot load, so `/users/me/` is requested once.
//

// 3rd party imports
//
import { defineStore } from "pinia";
import { computed, ref } from "vue";

// app imports
//
import { describeError } from "@/api/errors";
import type { BankAccount } from "@/models/bankAccount";
import { useBankAccountsStore } from "@/stores/bankAccounts";
import { useSessionStore } from "@/stores/session";

////////////////////////////////////////////////////////////////////////
//
const STORAGE_KEY = "mibudge.activeBankAccountId";

function readStored(): string | null {
  try {
    return window.sessionStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeStored(id: string | null): void {
  try {
    if (id) window.sessionStorage.setItem(STORAGE_KEY, id);
    else window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Storage can be unavailable (private mode); the choice then lasts
    // for this page load only.
  }
}

////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////
//
export const useAccountContextStore = defineStore("accountContext", () => {
  const bankAccounts = useBankAccountsStore();
  const session = useSessionStore();

  ////////////////////////////////////////////////////////////////////
  //
  const activeBankAccountId = ref<string | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);

  const accounts = computed<BankAccount[]>(() => bankAccounts.all);

  const activeBankAccount = computed<BankAccount | null>(() =>
    bankAccounts.byId(activeBankAccountId.value),
  );

  const unallocatedBudgetId = computed<string | null>(
    () => activeBankAccount.value?.unallocatedBudgetId ?? null,
  );

  ////////////////////////////////////////////////////////////////////
  //
  function setActive(id: string | null): void {
    activeBankAccountId.value = id;
    writeStored(id);
  }

  ////////////////////////////////////////////////////////////////////
  //
  // Load accounts and pick the active one.  Runs once per session
  // unless `force` is set.
  //
  async function init(force = false): Promise<void> {
    if (!force && bankAccounts.loaded && activeBankAccountId.value) return;
    loading.value = true;
    error.value = null;
    try {
      const [list, user] = await Promise.all([bankAccounts.loadAll(force), session.loadUser()]);
      const valid = new Set(list.map((a) => a.id));
      const stored = readStored();
      let chosen: string | null = null;
      if (stored && valid.has(stored)) chosen = stored;
      else if (user?.defaultBankAccountId && valid.has(user.defaultBankAccountId)) {
        chosen = user.defaultBankAccountId;
      } else chosen = list[0]?.id ?? null;
      setActive(chosen);
    } catch (err) {
      error.value = describeError(err, "Failed to load bank accounts.");
    } finally {
      loading.value = false;
    }
  }

  ////////////////////////////////////////////////////////////////////
  //
  // Refetch the account list (after a rename, create or delete).  When
  // the active account is gone, the first remaining account becomes
  // active.
  //
  async function refresh(): Promise<void> {
    const list = await bankAccounts.refresh();
    if (activeBankAccountId.value && !list.some((a) => a.id === activeBankAccountId.value)) {
      setActive(list[0]?.id ?? null);
    }
  }

  ////////////////////////////////////////////////////////////////////
  //
  function reset(): void {
    activeBankAccountId.value = null;
    loading.value = false;
    error.value = null;
    writeStored(null);
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
    reset,
  };
});
