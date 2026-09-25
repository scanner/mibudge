//
// Transaction allocations (`/api/v1/allocations/`): read-only.  API
// layer.  Allocations change through `transactions.split`.
//

// app imports
//
import type { AllocationDto, AllocationListQuery, Page } from "@/api/dto";
import type { HttpClient } from "@/api/http";
import { V1 } from "./paths";

////////////////////////////////////////////////////////////////////////
//
export function allocationsResource(http: HttpClient) {
  return {
    list(query?: AllocationListQuery): Promise<Page<AllocationDto>> {
      return http.get(`${V1}/allocations/`, query);
    },
  };
}
