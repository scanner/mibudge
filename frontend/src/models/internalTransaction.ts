//
// Internal transactions: budget-to-budget transfers within an account.
// Model layer: domain type and DTO mappers for
// `/api/v1/internal-transactions/`.
//

// app imports
//
import type {
  InternalTransactionCreateDto,
  InternalTransactionDto,
} from "@/api/dto";
import { DEFAULT_CURRENCY, Money } from "@/domain/money";

////////////////////////////////////////////////////////////////////////
//
export interface InternalTransaction {
  id: string;
  bankAccountId: string;
  // Always positive; the direction is `srcBudgetId` → `dstBudgetId`.
  amount: Money;
  srcBudgetId: string;
  dstBudgetId: string;
  // Instant the transfer takes effect (ISO datetime).
  effectiveDate: string;
  // Each budget's balance right after the transfer.
  srcBudgetBalance: Money;
  dstBudgetBalance: Money;
  createdAt: string;
}

////////////////////////////////////////////////////////////////////////
//
export function internalTransactionFromDto(
  dto: InternalTransactionDto,
): InternalTransaction {
  const currency = dto.amount_currency || DEFAULT_CURRENCY;
  return {
    id: dto.id,
    bankAccountId: dto.bank_account,
    amount: Money.of(dto.amount, currency),
    srcBudgetId: dto.src_budget,
    dstBudgetId: dto.dst_budget,
    effectiveDate: dto.effective_date ?? dto.created_at,
    srcBudgetBalance: Money.of(
      dto.src_budget_balance,
      dto.src_budget_balance_currency || currency,
    ),
    dstBudgetBalance: Money.of(
      dto.dst_budget_balance,
      dto.dst_budget_balance_currency || currency,
    ),
    createdAt: dto.created_at,
  };
}

////////////////////////////////////////////////////////////////////////
//
export interface TransferInput {
  bankAccountId: string;
  srcBudgetId: string;
  dstBudgetId: string;
  amount: Money;
}

export function transferToCreateDto(
  input: TransferInput,
): InternalTransactionCreateDto {
  return {
    bank_account: input.bankAccountId,
    src_budget: input.srcBudgetId,
    dst_budget: input.dstBudgetId,
    amount: input.amount.abs().toDecimalString(),
  };
}

////////////////////////////////////////////////////////////////////////
//
// The transfer's amount from one budget's point of view: positive when
// the budget received it, negative when it sent it.
//
export function amountRelativeTo(
  itx: InternalTransaction,
  budgetId: string,
): Money {
  return itx.dstBudgetId === budgetId ? itx.amount : itx.amount.negated();
}
