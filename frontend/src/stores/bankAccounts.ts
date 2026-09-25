//
// Bank-account entity cache.  Store layer.
//
// Holds the user's accounts as models, in list order.  `loadAll()`
// fetches the list once per session; `invalidate()` marks it stale so
// the next `loadAll()` refetches, and `refresh()` refetches now.
// Mutations (create, update, remove) go through here so every reader
// -- the account switcher, the top bar, the account pages -- sees the
// change.
//

// 3rd party imports
//
import { defineStore } from "pinia";
import { computed, ref } from "vue";

// app imports
//
import { api } from "@/api";
import type { BankAccount, BankAccountInput, BankAccountUpdate } from "@/models/bankAccount";
import {
  bankAccountFromDto,
  bankAccountToCreateDto,
  bankAccountToUpdateDto,
} from "@/models/bankAccount";

////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////
//
export const useBankAccountsStore = defineStore("bankAccounts", () => {
  const accounts = ref<BankAccount[]>([]);
  const loaded = ref(false);

  const all = computed(() => accounts.value);

  ////////////////////////////////////////////////////////////////////
  //
  function byId(id: string | null | undefined): BankAccount | null {
    if (!id) return null;
    return accounts.value.find((a) => a.id === id) ?? null;
  }

  function upsert(account: BankAccount): void {
    const idx = accounts.value.findIndex((a) => a.id === account.id);
    if (idx === -1) accounts.value = [...accounts.value, account];
    else accounts.value = accounts.value.map((a, i) => (i === idx ? account : a));
  }

  function setAll(list: BankAccount[]): void {
    accounts.value = list;
    loaded.value = true;
  }

  ////////////////////////////////////////////////////////////////////
  //
  // The account list, fetched on first use (or when stale / forced).
  //
  async function loadAll(force = false): Promise<BankAccount[]> {
    if (loaded.value && !force) return accounts.value;
    const first = await api.bankAccounts.list();
    setAll((await api.pages.all(first)).map(bankAccountFromDto));
    return accounts.value;
  }

  function refresh(): Promise<BankAccount[]> {
    return loadAll(true);
  }

  function invalidate(): void {
    loaded.value = false;
  }

  ////////////////////////////////////////////////////////////////////
  //
  async function fetchOne(id: string): Promise<BankAccount> {
    const account = bankAccountFromDto(await api.bankAccounts.get(id));
    upsert(account);
    return account;
  }

  async function create(input: BankAccountInput): Promise<BankAccount> {
    const account = bankAccountFromDto(
      await api.bankAccounts.create(bankAccountToCreateDto(input)),
    );
    upsert(account);
    return account;
  }

  async function update(id: string, patch: BankAccountUpdate): Promise<BankAccount> {
    const account = bankAccountFromDto(
      await api.bankAccounts.update(id, bankAccountToUpdateDto(patch)),
    );
    upsert(account);
    return account;
  }

  async function remove(id: string): Promise<void> {
    await api.bankAccounts.remove(id);
    accounts.value = accounts.value.filter((a) => a.id !== id);
  }

  ////////////////////////////////////////////////////////////////////
  //
  function reset(): void {
    accounts.value = [];
    loaded.value = false;
  }

  // Pinia treats the returned refs as the store's state (devtools,
  // hydration, `$patch`), so the backing ref is returned too.
  return {
    accounts,
    all,
    loaded,
    byId,
    upsert,
    setAll,
    loadAll,
    refresh,
    invalidate,
    fetchOne,
    create,
    update,
    remove,
    reset,
  };
});
