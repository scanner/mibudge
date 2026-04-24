//
// Currencies list endpoint (ISO 4217 codes accepted by the backend).
//
// TODO: GAP — the spec calls for GET /api/v1/currencies/ but the
//       backend currencies endpoint is still outstanding
//       (see task-mibudge-rest-api).  For now this module is a
//       placeholder so call sites have a stable import path.
//

import { useAuthStore } from "@/stores/auth";
import type { Paginated } from "@/types/api";

////////////////////////////////////////////////////////////////////////
//
export interface Currency {
  code: string;
  name: string;
}

////////////////////////////////////////////////////////////////////////
//
export function listCurrencies(): Promise<Paginated<Currency>> {
  return useAuthStore().request<Paginated<Currency>>("/currencies/");
}
