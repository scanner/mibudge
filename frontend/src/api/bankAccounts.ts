//
// Bank accounts — full CRUD.  After creation, only `name` is mutable;
// all balance and currency fields are frozen (backend enforces this).
//

import { useAuthStore } from "@/stores/auth";
import type { BankAccount, Paginated } from "@/types/api";

////////////////////////////////////////////////////////////////////////
//
export function listBankAccounts(): Promise<Paginated<BankAccount>> {
  return useAuthStore().request<Paginated<BankAccount>>("/bank-accounts/");
}

////////////////////////////////////////////////////////////////////////
//
export function getBankAccount(id: string): Promise<BankAccount> {
  return useAuthStore().request<BankAccount>(`/bank-accounts/${id}/`);
}

////////////////////////////////////////////////////////////////////////
//
export function createBankAccount(body: Partial<BankAccount>): Promise<BankAccount> {
  return useAuthStore().request<BankAccount>("/bank-accounts/", {
    method: "POST",
    body: body as BodyInit,
  });
}

////////////////////////////////////////////////////////////////////////
//
export function updateBankAccount(id: string, body: Partial<BankAccount>): Promise<BankAccount> {
  return useAuthStore().request<BankAccount>(`/bank-accounts/${id}/`, {
    method: "PATCH",
    body: body as BodyInit,
  });
}

////////////////////////////////////////////////////////////////////////
//
export function deleteBankAccount(id: string): Promise<null> {
  return useAuthStore().request<null>(`/bank-accounts/${id}/`, {
    method: "DELETE",
  });
}
