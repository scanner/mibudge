//
// Internal transactions (`/api/v1/internal-transactions/`):
// budget-to-budget transfers.  API layer.  Write-once: a transfer is
// undone by creating the reverse transfer.
//

// app imports
//
import type {
  InternalTransactionCreateDto,
  InternalTransactionDto,
  InternalTransactionListQuery,
  Page,
} from "@/api/dto";
import type { HttpClient } from "@/api/http";
import { V1 } from "./paths";

////////////////////////////////////////////////////////////////////////
//
export function internalTransactionsResource(http: HttpClient) {
  return {
    list(
      query?: InternalTransactionListQuery,
    ): Promise<Page<InternalTransactionDto>> {
      return http.get(`${V1}/internal-transactions/`, query);
    },

    create(
      body: InternalTransactionCreateDto,
    ): Promise<InternalTransactionDto> {
      return http.post(`${V1}/internal-transactions/`, body);
    },
  };
}
