//
// DTO (wire-format) types for the REST API, named from the generated
// `api/schema.d.ts`.  API layer.
//
// A DTO is exactly what the server sends or accepts: snake_case keys,
// money as decimal strings with a sibling `*_currency`, dates as ISO
// strings.  Only `api/resources/` and `models/` use these; the rest of
// the SPA works with the domain models in `models/`.
//
// Nothing here hand-writes a response shape except where the schema
// cannot express it; each such type says why.
//

// app imports
//
import type { components, operations } from "@/api/schema";

type Schemas = components["schemas"];

////////////////////////////////////////////////////////////////////////
//
// DRF's pagination envelope.  The schema marks `next` / `previous`
// optional; the server always sends them (possibly `null`).
//
export interface Page<T> {
  count: number;
  next?: string | null;
  previous?: string | null;
  results: T[];
}

////////////////////////////////////////////////////////////////////////
//
export type UserDto = Schemas["User"];
export type UserUpdateDto = Schemas["PatchedUserRequest"];
export type ChangePasswordDto = Schemas["ChangePasswordRequest"];

export type BankDto = Schemas["Bank"];

export type BankAccountDto = Schemas["BankAccount"];
export type BankAccountCreateDto = Schemas["BankAccountRequest"];
export type BankAccountUpdateDto = Schemas["PatchedBankAccountRequest"];

export type BudgetDto = Schemas["Budget"];
export type BudgetCreateDto = Schemas["BudgetRequest"];
export type BudgetUpdateDto = Schemas["PatchedBudgetRequest"];

export type TransactionDto = Schemas["Transaction"];
export type TransactionUpdateDto = Schemas["PatchedTransactionRequest"];

export type AllocationDto = Schemas["TransactionAllocation"];

export type InternalTransactionDto = Schemas["InternalTransaction"];
export type InternalTransactionCreateDto = Schemas["InternalTransactionRequest"];

export type TransactionCategoryDto = Schemas["TransactionCategory"];

export type InvitationDto = Schemas["BankAccountInvitation"];

export type ApiKeyDto = Schemas["APIKey"];
export type ApiKeyCreatedDto = Schemas["APIKeyCreated"];
export type ApiKeyCreateDto = Schemas["APIKeyCreateRequest"];

export type NotificationPreferenceDto = Schemas["NotificationPreference"];
export type ChannelPreferenceDto = Schemas["ChannelPreference"];
export type DeliveryModeDto = Schemas["DeliveryModeEnum"];
export type DigestFrequencyDto = Schemas["DigestFrequencyEnum"];

// Enums the domain layer mirrors (checked in `models/`).
export type AccountTypeDto = Schemas["AccountTypeEnum"];
export type BudgetTypeDto = Schemas["BudgetTypeEnum"];
export type FundingTypeDto = Schemas["FundingTypeEnum"];
export type FundingPaceDto = Schemas["FundingPaceEnum"];
export type TransactionTypeDto = Schemas["TransactionTypeEnum"];

////////////////////////////////////////////////////////////////////////
//
// Inline response bodies the schema declares without a named component.
//
export type FundingSummaryDto =
  operations["bank_accounts_funding_summary_retrieve"]["responses"][200]["content"]["application/json"];
export type FundingRunResultDto =
  operations["bank_accounts_run_funding_create"]["responses"][200]["content"]["application/json"];

// `POST /api/token/` and `/api/token/refresh/` answer `{access}`; the
// schema documents no response body for them.
export interface AccessTokenDto {
  access: string;
}

////////////////////////////////////////////////////////////////////////
//
// Query parameters of the list endpoints.
//
export type BudgetListQuery = NonNullable<operations["budgets_list"]["parameters"]["query"]>;
export type TransactionListQuery = NonNullable<
  operations["transactions_list"]["parameters"]["query"]
>;
export type AllocationListQuery = NonNullable<
  operations["allocations_list"]["parameters"]["query"]
>;
export type InternalTransactionListQuery = NonNullable<
  operations["internal_transactions_list"]["parameters"]["query"]
>;
export type TransactionCategoryListQuery = NonNullable<
  operations["transaction_categories_list"]["parameters"]["query"]
>;
