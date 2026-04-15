//
// Budgets — full CRUD.  Immutable after creation: `bank_account`,
// `budget_type`.  The unallocated budget cannot be deleted (backend
// returns 403).
//

import { useAuthStore } from "@/stores/auth";
import { qs } from "@/api/util";
import type { Budget, BudgetListParams, Paginated } from "@/types/api";

////////////////////////////////////////////////////////////////////////
//
export function listBudgets(params?: BudgetListParams): Promise<Paginated<Budget>> {
  return useAuthStore().request<Paginated<Budget>>(`/budgets/${qs(params)}`);
}

////////////////////////////////////////////////////////////////////////
//
export function getBudget(id: string): Promise<Budget> {
  return useAuthStore().request<Budget>(`/budgets/${id}/`);
}

////////////////////////////////////////////////////////////////////////
//
export function createBudget(body: Partial<Budget>): Promise<Budget> {
  return useAuthStore().request<Budget>("/budgets/", {
    method: "POST",
    body: body as BodyInit,
  });
}

////////////////////////////////////////////////////////////////////////
//
export function updateBudget(id: string, body: Partial<Budget>): Promise<Budget> {
  return useAuthStore().request<Budget>(`/budgets/${id}/`, {
    method: "PATCH",
    body: body as BodyInit,
  });
}

////////////////////////////////////////////////////////////////////////
//
export function deleteBudget(id: string): Promise<null> {
  return useAuthStore().request<null>(`/budgets/${id}/`, {
    method: "DELETE",
  });
}
