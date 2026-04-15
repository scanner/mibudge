//
// Banks are read-only reference data shared across all users.
//

import { useAuthStore } from "@/stores/auth";
import type { Bank, Paginated } from "@/types/api";

////////////////////////////////////////////////////////////////////////
//
export function listBanks(): Promise<Paginated<Bank>> {
  return useAuthStore().request<Paginated<Bank>>("/banks/");
}

////////////////////////////////////////////////////////////////////////
//
export function getBank(id: string): Promise<Bank> {
  return useAuthStore().request<Bank>(`/banks/${id}/`);
}
