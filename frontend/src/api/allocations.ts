//
// Transaction allocations — listing only.  Mutation is handled by the
// declarative `POST /transactions/<id>/splits/` endpoint (see
// `splitTransaction` in `@/api/transactions`).
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
