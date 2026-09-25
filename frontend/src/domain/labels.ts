//
// Enumerations shared across the SPA and their human-readable labels.
// Domain layer: pure TypeScript.
//
// The unions mirror the enums in `docs/openapi.yaml`; the model layer
// checks at compile time that they stay assignable to the generated
// schema types.
//

////////////////////////////////////////////////////////////////////////
//
export type AccountType = "C" | "S" | "X";

export const ACCOUNT_TYPE_LABELS: Record<AccountType, string> = {
  C: "Checking",
  S: "Savings",
  X: "Credit card",
};

////////////////////////////////////////////////////////////////////////
//
// Label for an account type, falling back to the raw code for a value
// this build does not know.
//
export function accountTypeLabel(type: string): string {
  return ACCOUNT_TYPE_LABELS[type as AccountType] ?? type;
}

////////////////////////////////////////////////////////////////////////
//
// `"Checking ····1234"`: the type label plus the last four digits of
// the account number when there is one.
//
export function accountTypeMeta(
  type: string,
  accountNumber: string | null,
): string {
  const label = accountTypeLabel(type);
  return accountNumber ? `${label} ····${accountNumber.slice(-4)}` : label;
}

////////////////////////////////////////////////////////////////////////
//
// G = Goal, R = Recurring, A = associated fill-up goal of a recurring
// budget, C = Capped.
//
export type BudgetType = "G" | "R" | "A" | "C";

export const BUDGET_TYPE_LABELS: Record<BudgetType, string> = {
  G: "Goal",
  R: "Recurring",
  A: "Fill-up",
  C: "Capped",
};

////////////////////////////////////////////////////////////////////////
//
// D = funded toward a target date, F = a fixed amount per event.
//
export type FundingType = "D" | "F";

export type FundingPace = "ahead" | "on_track" | "behind";

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
// Label for a transaction type; `""` for none, the raw value for a
// type this build does not know.
//
export function transactionTypeLabel(type: string | null | undefined): string {
  if (!type) return "";
  return TRANSACTION_TYPE_LABELS[type as TransactionType] ?? type;
}
