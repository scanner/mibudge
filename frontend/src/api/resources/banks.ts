//
// Banks (`/api/v1/banks/`): read-only reference data.  API layer.
//

// app imports
//
import type { BankDto, Page } from "@/api/dto";
import type { HttpClient } from "@/api/http";
import { V1 } from "./paths";

////////////////////////////////////////////////////////////////////////
//
export function banksResource(http: HttpClient) {
  return {
    list(): Promise<Page<BankDto>> {
      return http.get(`${V1}/banks/`);
    },

    get(id: string): Promise<BankDto> {
      return http.get(`${V1}/banks/${id}/`);
    },
  };
}
