//
// Bank accounts (`/api/v1/bank-accounts/`) and their funding actions.
// API layer.
//
// After creation only `name`, `account_number` and
// `auto_funding_enabled` change; balances, currency, bank and type are
// fixed.
//

// app imports
//
import type {
  BankAccountCreateDto,
  BankAccountDto,
  BankAccountUpdateDto,
  FundingRunResultDto,
  FundingSummaryDto,
  Page,
} from "@/api/dto";
import type { HttpClient } from "@/api/http";
import { V1 } from "./paths";

////////////////////////////////////////////////////////////////////////
//
export function bankAccountsResource(http: HttpClient) {
  return {
    list(): Promise<Page<BankAccountDto>> {
      return http.get(`${V1}/bank-accounts/`);
    },

    get(id: string): Promise<BankAccountDto> {
      return http.get(`${V1}/bank-accounts/${id}/`);
    },

    create(body: BankAccountCreateDto): Promise<BankAccountDto> {
      return http.post(`${V1}/bank-accounts/`, body);
    },

    update(id: string, body: BankAccountUpdateDto): Promise<BankAccountDto> {
      return http.patch(`${V1}/bank-accounts/${id}/`, body);
    },

    remove(id: string): Promise<null> {
      return http.delete(`${V1}/bank-accounts/${id}/`);
    },

    fundingSummary(id: string): Promise<FundingSummaryDto> {
      return http.get(`${V1}/bank-accounts/${id}/funding-summary/`);
    },

    runFunding(id: string): Promise<FundingRunResultDto> {
      return http.post(`${V1}/bank-accounts/${id}/run-funding/`);
    },
  };
}
