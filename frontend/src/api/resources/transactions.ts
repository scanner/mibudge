//
// Transactions (`/api/v1/transactions/`).  API layer.
//
// Transactions are imported from the bank; the SPA edits only
// `description`, `memo` and the `image` / `document` attachments, and
// re-allocates them with the declarative splits endpoint.
//

// app imports
//
import type {
  AllocationDto,
  Page,
  TransactionDto,
  TransactionListQuery,
  TransactionUpdateDto,
} from "@/api/dto";
import type { HttpClient } from "@/api/http";
import { V1 } from "./paths";

////////////////////////////////////////////////////////////////////////
//
export function transactionsResource(http: HttpClient) {
  return {
    list(query?: TransactionListQuery): Promise<Page<TransactionDto>> {
      return http.get(`${V1}/transactions/`, query);
    },

    get(id: string): Promise<TransactionDto> {
      return http.get(`${V1}/transactions/${id}/`);
    },

    update(id: string, body: Pick<TransactionUpdateDto, "description" | "memo">) {
      return http.patch<TransactionDto>(`${V1}/transactions/${id}/`, body);
    },

    // Multipart upload of a photo (`image`) or document (`document`).
    //
    uploadAttachment(id: string, field: "image" | "document", file: File) {
      const form = new FormData();
      form.append(field, file);
      return http.request<TransactionDto>(`${V1}/transactions/${id}/`, { method: "PATCH", form });
    },

    // Replace the transaction's allocations with `splits` (budget id →
    // positive amount); the remainder goes to Unallocated.  Answers the
    // resulting allocations as a plain array (the schema calls it a
    // page).
    //
    split(id: string, splits: Record<string, string>): Promise<AllocationDto[]> {
      return http.post(`${V1}/transactions/${id}/splits/`, { splits });
    },
  };
}
