//
// Bank accounts and their funding summary / funding-run result.  Model
// layer: domain types and DTO mappers for `/api/v1/bank-accounts/`.
//

// app imports
//
import type {
  AccountTypeDto,
  BankAccountCreateDto,
  BankAccountDto,
  BankAccountUpdateDto,
  FundingRunResultDto,
  FundingSummaryDto,
} from "@/api/dto";
import type { LocalDate } from "@/domain/dates";
import { toLocalDate } from "@/domain/dates";
import type { AccountType } from "@/domain/labels";
import { DEFAULT_CURRENCY, Money } from "@/domain/money";
import type { Equal, Expect } from "@/models/schemaCheck";

export type AccountTypeMatchesSchema = Expect<
  Equal<AccountType, AccountTypeDto>
>;

////////////////////////////////////////////////////////////////////////
//
export interface BankAccount {
  id: string;
  name: string;
  bankId: string;
  // Owner identifiers as the API lists them.
  owners: string[];
  accountType: AccountType;
  accountNumber: string | null;
  currency: string;
  postedBalance: Money;
  availableBalance: Money;
  // Every account gets an "Unallocated" budget on creation; `null` only
  // in the moment before the server has created it.
  unallocatedBudgetId: string | null;
  autoFundingEnabled: boolean;
  // Instant of the last import (ISO datetime), if any.
  lastImportedAt: string | null;
  // Last posted date the imported data covers.
  lastPostedThrough: LocalDate | null;
  createdAt: string;
}

////////////////////////////////////////////////////////////////////////
//
export function bankAccountFromDto(dto: BankAccountDto): BankAccount {
  const currency = dto.currency || DEFAULT_CURRENCY;
  return {
    id: dto.id,
    name: dto.name,
    bankId: dto.bank,
    owners: dto.owners ?? [],
    accountType: dto.account_type ?? "C",
    accountNumber: dto.account_number ?? null,
    currency,
    postedBalance: Money.of(
      dto.posted_balance,
      dto.posted_balance_currency || currency,
    ),
    availableBalance: Money.of(
      dto.available_balance,
      dto.available_balance_currency || currency,
    ),
    unallocatedBudgetId: dto.unallocated_budget ?? null,
    autoFundingEnabled: dto.auto_funding_enabled ?? true,
    lastImportedAt: dto.last_imported_at ?? null,
    lastPostedThrough: toLocalDate(dto.last_posted_through),
    createdAt: dto.created_at,
  };
}

////////////////////////////////////////////////////////////////////////
//
export interface BankAccountInput {
  accountType: AccountType;
  name: string;
  bankId: string;
  currency: string;
  accountNumber: string;
  // Opening balances; omitted when `null` (the server defaults to 0).
  postedBalance: Money | null;
  availableBalance: Money | null;
}

export function bankAccountToCreateDto(
  input: BankAccountInput,
): BankAccountCreateDto {
  const dto: BankAccountCreateDto = {
    account_type: input.accountType,
    name: input.name,
    bank: input.bankId,
    currency: input.currency,
    account_number: input.accountNumber,
  };
  if (input.postedBalance)
    dto.posted_balance = input.postedBalance.toDecimalString();
  if (input.availableBalance)
    dto.available_balance = input.availableBalance.toDecimalString();
  return dto;
}

////////////////////////////////////////////////////////////////////////
//
export type BankAccountUpdate = Partial<
  Pick<BankAccount, "name" | "accountNumber" | "autoFundingEnabled">
>;

export function bankAccountToUpdateDto(
  update: BankAccountUpdate,
): BankAccountUpdateDto {
  const dto: BankAccountUpdateDto = {};
  if (update.name !== undefined) dto.name = update.name;
  if (update.accountNumber !== undefined)
    dto.account_number = update.accountNumber || null;
  if (update.autoFundingEnabled !== undefined) {
    dto.auto_funding_enabled = update.autoFundingEnabled;
  }
  return dto;
}

////////////////////////////////////////////////////////////////////////
//
// The next funding event across an account's budgets, grouped by
// schedule.  `total` is the amount the next event will move.
//
export interface FundingScheduleEntry {
  schedule: string;
  nextDate: LocalDate | null;
  total: Money;
  budgetCount: number;
}

export interface FundingSummary {
  schedules: FundingScheduleEntry[];
  total: Money;
}

export function fundingSummaryFromDto(dto: FundingSummaryDto): FundingSummary {
  const currency = dto.currency || DEFAULT_CURRENCY;
  return {
    schedules: (dto.schedules ?? []).map((s) => ({
      schedule: s.schedule ?? "",
      nextDate: toLocalDate(s.next_date),
      total: Money.of(s.total_amount, s.currency || currency),
      budgetCount: s.budget_count ?? 0,
    })),
    total: Money.of(dto.total_amount, currency),
  };
}

////////////////////////////////////////////////////////////////////////
//
export interface FundingRunResult {
  transfers: number;
  occurrencesCompleted: number;
  occurrencesPartial: number;
  warnings: string[];
  // Names of paused budgets the run skipped.
  skippedBudgets: string[];
}

export function fundingRunResultFromDto(
  dto: FundingRunResultDto,
): FundingRunResult {
  return {
    transfers: dto.transfers ?? 0,
    occurrencesCompleted: dto.occurrences_completed ?? 0,
    occurrencesPartial: dto.occurrences_partial ?? 0,
    warnings: dto.warnings ?? [],
    skippedBudgets: dto.skipped_budgets ?? [],
  };
}

////////////////////////////////////////////////////////////////////////
//
// A run that moved nothing and reported nothing.
//
export function fundingRunIsNoop(result: FundingRunResult): boolean {
  return (
    result.transfers === 0 &&
    result.warnings.length === 0 &&
    result.skippedBudgets.length === 0
  );
}
