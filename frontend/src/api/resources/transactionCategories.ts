//
// Transaction categories (`/api/v1/transaction-categories/`): the
// global base set plus categories created by the account's owners.
// API layer.
//

// app imports
//
import type { Page, TransactionCategoryDto, TransactionCategoryListQuery } from "@/api/dto";
import type { HttpClient } from "@/api/http";
import { V1 } from "./paths";

////////////////////////////////////////////////////////////////////////
//
export function transactionCategoriesResource(http: HttpClient) {
  return {
    list(query?: TransactionCategoryListQuery): Promise<Page<TransactionCategoryDto>> {
      return http.get(`${V1}/transaction-categories/`, query);
    },

    get(id: string): Promise<TransactionCategoryDto> {
      return http.get(`${V1}/transaction-categories/${id}/`);
    },
  };
}
