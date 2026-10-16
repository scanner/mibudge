//
// Bank-account entity cache.  Store layer.
//
// Holds the user's accounts as models, in list order.  `loadAll()`
// fetches the list once per session; `invalidate()` marks it stale so
// the next `loadAll()` refetches, and `refresh()` refetches now.
// Mutations (create, update, remove) go through here so every reader
// -- the account switcher, the top bar, the account pages -- sees the
// change.  Writes follow `createWriteOrder`: a fetch answer older than
// an account's last mutation or fetch keeps the cached account, and a
// list answer older than the last create or remove is dropped whole.
// Concurrent list loads share one request.
//

// 3rd party imports
//
import { defineStore } from "pinia";
import { computed, ref } from "vue";

// app imports
//
import { api } from "@/api";
import type {
  BankAccount,
  BankAccountInput,
  BankAccountUpdate,
} from "@/models/bankAccount";
import {
  bankAccountFromDto,
  bankAccountToCreateDto,
  bankAccountToUpdateDto,
} from "@/models/bankAccount";
import { createSessionGuard } from "@/stores/reset";
import { createWriteOrder } from "@/stores/writeOrder";

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
    else
      accounts.value = accounts.value.map((a, i) => (i === idx ? account : a));
  }

  function setAll(list: BankAccount[]): void {
    accounts.value = list;
    loaded.value = true;
  }

  ////////////////////////////////////////////////////////////////////
  //
  // A request writes its answer to the list only if no sign-out
  // (`reset()`) happened while it was in flight.
  //
  const guard = createSessionGuard();
  const whileCurrent = guard.whileCurrent;
  const order = createWriteOrder();
  // The ticket of the newest change to which accounts are listed.
  let listWrittenAt = 0;
  let listRequest: Promise<BankAccount[]> | null = null;

  ////////////////////////////////////////////////////////////////////
  //
  // The account list, fetched on first use (or when stale / forced).
  //
  async function loadAll(force = false): Promise<BankAccount[]> {
    if (loaded.value && !force) return accounts.value;
    listRequest ??= fetchAll().finally(() => {
      listRequest = null;
    });
    return listRequest;
  }

  async function fetchAll(): Promise<BankAccount[]> {
    const ticket = order.ticket();
    const put = whileCurrent(setAll);
    const first = await api.bankAccounts.list();
    const list = (await api.pages.all(first)).map(bankAccountFromDto);
    if (ticket < listWrittenAt) return accounts.value;
    listWrittenAt = ticket;
    // An account with a newer answer cached keeps it.
    put(list.map((a) => (order.accept(a.id, ticket) ? a : (byId(a.id) ?? a))));
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
    const ticket = order.ticket();
    const put = whileCurrent(upsert);
    const account = bankAccountFromDto(await api.bankAccounts.get(id));
    if (order.accept(id, ticket)) put(account);
    return account;
  }

  async function create(input: BankAccountInput): Promise<BankAccount> {
    const put = whileCurrent(upsert);
    const account = bankAccountFromDto(
      await api.bankAccounts.create(bankAccountToCreateDto(input)),
    );
    order.written(account.id);
    listWrittenAt = order.ticket();
    put(account);
    return account;
  }

  async function update(
    id: string,
    patch: BankAccountUpdate,
  ): Promise<BankAccount> {
    const put = whileCurrent(upsert);
    const account = bankAccountFromDto(
      await order.mutating([id], () =>
        api.bankAccounts.update(id, bankAccountToUpdateDto(patch)),
      ),
    );
    put(account);
    return account;
  }

  async function remove(id: string): Promise<void> {
    await api.bankAccounts.remove(id);
    listWrittenAt = order.ticket();
    accounts.value = accounts.value.filter((a) => a.id !== id);
  }

  ////////////////////////////////////////////////////////////////////
  //
  function reset(): void {
    guard.bump();
    order.clear();
    listWrittenAt = 0;
    listRequest = null;
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
