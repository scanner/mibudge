//
// Transaction allocations — full CRUD, subject to the constraint that
// the sum of allocations for a transaction must not exceed the
// transaction amount.  The last allocation on a transaction cannot be
// deleted.  See GAP-4 for the `amount` mutability question.
//

import { useAuthStore } from "@/stores/auth";
import { qs } from "@/api/util";
import type { AllocationListParams, Paginated, TransactionAllocation } from "@/types/api";

////////////////////////////////////////////////////////////////////////
//
export function listAllocations(
  params?: AllocationListParams,
): Promise<Paginated<TransactionAllocation>> {
  return useAuthStore().request<Paginated<TransactionAllocation>>(`/allocations/${qs(params)}`);
}

////////////////////////////////////////////////////////////////////////
//
export function getAllocation(id: string): Promise<TransactionAllocation> {
  return useAuthStore().request<TransactionAllocation>(`/allocations/${id}/`);
}

////////////////////////////////////////////////////////////////////////
//
export function createAllocation(
  body: Partial<TransactionAllocation>,
): Promise<TransactionAllocation> {
  return useAuthStore().request<TransactionAllocation>("/allocations/", {
    method: "POST",
    body: body as BodyInit,
  });
}

////////////////////////////////////////////////////////////////////////
//
export function updateAllocation(
  id: string,
  body: Partial<TransactionAllocation>,
): Promise<TransactionAllocation> {
  return useAuthStore().request<TransactionAllocation>(`/allocations/${id}/`, {
    method: "PATCH",
    body: body as BodyInit,
  });
}

////////////////////////////////////////////////////////////////////////
//
export function deleteAllocation(id: string): Promise<null> {
  return useAuthStore().request<null>(`/allocations/${id}/`, {
    method: "DELETE",
  });
}
