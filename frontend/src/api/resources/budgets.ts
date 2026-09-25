//
// Budgets (`/api/v1/budgets/`).  API layer.
//
// `bank_account` and `budget_type` are fixed after creation.  Budgets
// are archived, not deleted (archiving moves the balance to
// Unallocated).
//

// app imports
//
import type { BudgetCreateDto, BudgetDto, BudgetListQuery, BudgetUpdateDto, Page } from "@/api/dto";
import type { HttpClient } from "@/api/http";
import { V1 } from "./paths";

////////////////////////////////////////////////////////////////////////
//
export function budgetsResource(http: HttpClient) {
  return {
    list(query?: BudgetListQuery): Promise<Page<BudgetDto>> {
      return http.get(`${V1}/budgets/`, query);
    },

    get(id: string): Promise<BudgetDto> {
      return http.get(`${V1}/budgets/${id}/`);
    },

    create(body: BudgetCreateDto): Promise<BudgetDto> {
      return http.post(`${V1}/budgets/`, body);
    },

    update(id: string, body: BudgetUpdateDto): Promise<BudgetDto> {
      return http.patch(`${V1}/budgets/${id}/`, body);
    },

    archive(id: string): Promise<BudgetDto> {
      return http.post(`${V1}/budgets/${id}/archive/`);
    },
  };
}
