//
// Internal transactions — write-once (create + read only).  To reverse
// a transfer, create a new internal transaction with src and dst
// budgets swapped.
//

import { useAuthStore } from "@/stores/auth";
import { qs } from "@/api/util";
import type { InternalTransaction, InternalTransactionListParams, Paginated } from "@/types/api";

////////////////////////////////////////////////////////////////////////
//
export function listInternalTransactions(
  params?: InternalTransactionListParams,
): Promise<Paginated<InternalTransaction>> {
  return useAuthStore().request<Paginated<InternalTransaction>>(
    `/internal-transactions/${qs(params)}`,
  );
}

////////////////////////////////////////////////////////////////////////
//
export function getInternalTransaction(id: string): Promise<InternalTransaction> {
  return useAuthStore().request<InternalTransaction>(`/internal-transactions/${id}/`);
}

////////////////////////////////////////////////////////////////////////
//
export function createInternalTransaction(
  body: Partial<InternalTransaction>,
): Promise<InternalTransaction> {
  return useAuthStore().request<InternalTransaction>("/internal-transactions/", {
    method: "POST",
    body: body as BodyInit,
  });
}
