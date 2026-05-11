//
// TypeScript types mirroring the DRF API schemas.
//
// These track `docs/openapi.yaml` by hand for now.  Monetary amounts
// are decimal strings (e.g. "142.80") — never parsed to Number for
// arithmetic (see UI_SPEC.md §8 and decimal.js usage notes).
//

////////////////////////////////////////////////////////////////////////
//
// Paginated list envelope returned by DRF's default pagination class.
//
export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

////////////////////////////////////////////////////////////////////////
//
export type AccountType = "C" | "S" | "X";
export type BudgetType = "G" | "R" | "A" | "C";

////////////////////////////////////////////////////////////////////////
//
export interface BankAccount {
  id: string;
  name: string;
  bank: string; // UUID
  owners: string[]; // list of user PKs — read-only, set server-side on create
  account_type: AccountType;
  account_number: string | null;
  currency: string;
  posted_balance: string;
  posted_balance_currency: string;
  available_balance: string;
  available_balance_currency: string;
  unallocated_budget: string;
  last_imported_at: string | null;
  last_posted_through: string | null;
  created_at: string;
  modified_at: string;
}

////////////////////////////////////////////////////////////////////////
//
export interface NextFunding {
  date: string; // ISO date string, e.g. "2026-05-01"
  amount: string; // decimal string
  amount_currency: string;
  deferred: boolean;
}

////////////////////////////////////////////////////////////////////////
//
export interface Budget {
  id: string;
  name: string;
  bank_account: string;
  budget_type: BudgetType;
  balance: string;
  balance_currency: string;
  target_balance: string | null;
  target_balance_currency: string;
  funding_amount: string | null;
  funding_amount_currency: string;
  funding_type: "D" | "F"; // D = Target Date, F = Fixed Amount
  target_date: string | null;
  with_fillup_goal: boolean;
  fillup_goal: string | null;
  complete: boolean;
  paused: boolean;
  archived: boolean;
  funding_schedule: string;
  // NOTE: field is spelled with a typo in the model and serializer.
  recurrence_schedule: string | null;
  memo: string | null;
  auto_spend: unknown;
  next_funding: NextFunding | null;
  created_at: string;
  modified_at: string;
}

////////////////////////////////////////////////////////////////////////
//
export interface FundingScheduleEntry {
  schedule: string; // RRULE string
  next_date: string; // ISO date
  total_amount: string; // decimal string
  currency: string;
  budget_count: number;
}

export interface FundingSummary {
  schedules: FundingScheduleEntry[];
  total_amount: string; // decimal string
  currency: string;
}

////////////////////////////////////////////////////////////////////////
//
export type TransactionType =
  | "signature_purchase"
  | "ach"
  | "round-up_transfer"
  | "protected_goal_account_transfer"
  | "fee"
  | "pin_purchase"
  | "signature_credit"
  | "interest_credit"
  | "shared_transfer"
  | "courtesy_credit"
  | "atm_withdrawal"
  | "bill_payment"
  | "bank_generated_credit"
  | "wire_transfer"
  | "check_deposit"
  | "check"
  | "c2c"
  | "migration_interbank_transfer"
  | "balance_sweep"
  | "ach_reversal"
  | "adjustment"
  | "signature_return"
  | "fx_order";

////////////////////////////////////////////////////////////////////////
//
// Human-friendly labels for TransactionType (UI_SPEC §9).  Any
// TransactionType not listed here falls back to the raw value.
//
export const TRANSACTION_TYPE_LABELS: Record<TransactionType, string> = {
  signature_purchase: "Signature purchase",
  ach: "ACH transfer",
  "round-up_transfer": "Round-up transfer",
  protected_goal_account_transfer: "Goal transfer",
  fee: "Fee",
  pin_purchase: "PIN purchase",
  signature_credit: "Credit",
  interest_credit: "Interest",
  shared_transfer: "Shared transfer",
  courtesy_credit: "Courtesy credit",
  atm_withdrawal: "ATM withdrawal",
  bill_payment: "Bill payment",
  bank_generated_credit: "Bank credit",
  wire_transfer: "Wire transfer",
  check_deposit: "Check deposit",
  check: "Check",
  c2c: "Card-to-card",
  migration_interbank_transfer: "Interbank transfer",
  balance_sweep: "Balance sweep",
  ach_reversal: "ACH reversal",
  adjustment: "Adjustment",
  signature_return: "Return",
  fx_order: "FX order",
};

////////////////////////////////////////////////////////////////////////
//
export interface Transaction {
  id: string;
  bank_account: string;
  amount: string;
  amount_currency: string;
  party: string | null;
  posted_date: string;
  transaction_date: string;
  transaction_type: TransactionType | "";
  pending: boolean;
  memo: string | null;
  raw_description: string;
  description: string;
  bank_account_posted_balance: string;
  bank_account_posted_balance_currency: string;
  bank_account_available_balance: string;
  bank_account_available_balance_currency: string;
  image: string | null;
  document: string | null;
  created_at: string;
  modified_at: string;
}

////////////////////////////////////////////////////////////////////////
//
// Matches `TransactionCategory.choices` on the backend.  Kept as an
// opaque string for now; expand into a literal union once the category
// picker UI is built.
//
export type CategoryEnum = string;

export interface TransactionAllocation {
  id: string;
  transaction: string;
  budget: string | null;
  amount: string;
  amount_currency: string;
  budget_balance: string;
  budget_balance_currency: string;
  category: CategoryEnum | null;
  memo: string | null;
  created_at: string;
  modified_at: string;
}

////////////////////////////////////////////////////////////////////////
//
export interface InternalTransaction {
  id: string;
  bank_account: string;
  amount: string;
  amount_currency: string;
  src_budget: string;
  dst_budget: string;
  actor: string;
  effective_date: string;
  src_budget_balance: string;
  src_budget_balance_currency: string;
  dst_budget_balance: string;
  dst_budget_balance_currency: string;
  created_at: string;
  modified_at: string;
}

////////////////////////////////////////////////////////////////////////
//
export interface Bank {
  id: string;
  name: string;
  routing_number?: string | null;
  default_currency?: string;
}

////////////////////////////////////////////////////////////////////////
//
export interface User {
  username: string;
  name: string;
  url: string;
  default_bank_account: string | null;
  timezone: string;
}

////////////////////////////////////////////////////////////////////////
//
// Query parameter shapes for list endpoints.  Use these rather than
// raw URLSearchParams objects so TypeScript catches typos.
//
export interface BudgetListParams {
  bank_account?: string;
  budget_type?: BudgetType;
  paused?: boolean;
  archived?: boolean;
  ordering?: string;
}

export interface TransactionListParams {
  bank_account?: string;
  pending?: boolean;
  transaction_type?: TransactionType;
  date_from?: string;
  date_to?: string;
  search?: string;
  ordering?: string;
  page?: number;
}

export interface AllocationListParams {
  bank_account?: string;
  transaction?: string;
  budget?: string;
  category?: string;
}

export interface InternalTransactionListParams {
  bank_account?: string;
  src_budget?: string;
  dst_budget?: string;
  budget?: string;
  date_from?: string;
  date_to?: string;
}
