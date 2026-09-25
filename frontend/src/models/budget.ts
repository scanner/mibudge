//
// Budgets (virtual envelopes).  Model layer: domain type and DTO
// mappers for `/api/v1/budgets/`, plus pure helpers over budget lists.
//
// A `Budget` satisfies `BudgetFigures`, so the status / progress / meta
// rules in `domain/budgetStatus` apply to it directly.
//

// app imports
//
import type {
  BudgetCreateDto,
  BudgetDto,
  BudgetTypeDto,
  BudgetUpdateDto,
  FundingPaceDto,
  FundingTypeDto,
} from "@/api/dto";
import type { BudgetFigures } from "@/domain/budgetStatus";
import type { LocalDate } from "@/domain/dates";
import { toLocalDate } from "@/domain/dates";
import type { BudgetType, FundingPace, FundingType } from "@/domain/labels";
import { DEFAULT_CURRENCY, Money } from "@/domain/money";
import type { Equal, Expect } from "@/models/schemaCheck";

export type BudgetTypeMatchesSchema = Expect<Equal<BudgetType, BudgetTypeDto>>;
export type FundingTypeMatchesSchema = Expect<
  Equal<FundingType, FundingTypeDto>
>;
export type FundingPaceMatchesSchema = Expect<
  Equal<FundingPace, FundingPaceDto>
>;

////////////////////////////////////////////////////////////////////////
//
export interface NextFunding {
  date: LocalDate;
  amount: Money;
}

////////////////////////////////////////////////////////////////////////
//
export interface Budget extends BudgetFigures {
  id: string;
  name: string;
  bankAccountId: string;
  budgetType: BudgetType;
  balance: Money;
  // Running net of transfers into the budget.  For goals this is the
  // true progress: spending lowers `balance` but not `fundedAmount`.
  fundedAmount: Money;
  targetBalance: Money | null;
  fundingAmount: Money | null;
  fundingType: FundingType;
  targetDate: LocalDate | null;
  // Id of the associated fill-up goal (type `A`) of a recurring budget.
  fillupGoalId: string | null;
  archived: boolean;
  archivedAt: string | null;
  complete: boolean;
  paused: boolean;
  fundingSchedule: string | null;
  recurrenceSchedule: string | null;
  memo: string | null;
  nextFunding: NextFunding | null;
  // Next refresh date of a recurring budget, computed server-side.
  nextRecurrence: LocalDate | null;
  fundingPace: FundingPace | null;
  createdAt: string;
}

////////////////////////////////////////////////////////////////////////
//
// `next_funding` is an untyped object in the schema; read the three
// fields the server sends and drop the value when any is unusable.
//
function nextFundingFromDto(
  raw: BudgetDto["next_funding"],
  currency: string,
): NextFunding | null {
  if (!raw) return null;
  const date = toLocalDate(typeof raw.date === "string" ? raw.date : null);
  if (!date || typeof raw.amount !== "string") return null;
  const amountCurrency =
    typeof raw.amount_currency === "string" ? raw.amount_currency : currency;
  return { date, amount: Money.of(raw.amount, amountCurrency) };
}

////////////////////////////////////////////////////////////////////////
//
export function budgetFromDto(dto: BudgetDto): Budget {
  const currency = dto.balance_currency || DEFAULT_CURRENCY;
  return {
    id: dto.id,
    name: dto.name,
    bankAccountId: dto.bank_account,
    budgetType: dto.budget_type ?? "G",
    balance: Money.of(dto.balance, currency),
    fundedAmount: Money.of(
      dto.funded_amount,
      dto.funded_amount_currency || currency,
    ),
    targetBalance: Money.ofNullable(
      dto.target_balance,
      dto.target_balance_currency || currency,
    ),
    fundingAmount: Money.ofNullable(
      dto.funding_amount,
      dto.funding_amount_currency || currency,
    ),
    fundingType: dto.funding_type ?? "D",
    targetDate: toLocalDate(dto.target_date),
    fillupGoalId: dto.fillup_goal ?? null,
    archived: dto.archived,
    archivedAt: dto.archived_at ?? null,
    complete: dto.complete,
    paused: dto.paused ?? false,
    fundingSchedule: dto.funding_schedule || null,
    recurrenceSchedule: dto.recurrence_schedule || null,
    memo: dto.memo ?? null,
    nextFunding: nextFundingFromDto(dto.next_funding, currency),
    nextRecurrence: toLocalDate(dto.next_recurrence),
    fundingPace: dto.funding_pace ?? null,
    createdAt: dto.created_at,
  };
}

////////////////////////////////////////////////////////////////////////
//
// The editable fields of a budget, as the budget form produces them.
// `null` clears a nullable field; `undefined` leaves it out of the
// request.
//
export interface BudgetInput {
  name?: string;
  budgetType?: BudgetType;
  bankAccountId?: string;
  targetBalance?: Money | null;
  targetDate?: LocalDate | null;
  fundingType?: FundingType;
  fundingAmount?: Money | null;
  fundingSchedule?: string;
  recurrenceSchedule?: string | null;
  paused?: boolean;
}

export function budgetToUpdateDto(input: BudgetInput): BudgetUpdateDto {
  const dto: BudgetUpdateDto = {};
  if (input.name !== undefined) dto.name = input.name;
  if (input.budgetType !== undefined) dto.budget_type = input.budgetType;
  if (input.bankAccountId !== undefined) dto.bank_account = input.bankAccountId;
  if (input.targetBalance)
    dto.target_balance = input.targetBalance.toDecimalString();
  if (input.targetDate !== undefined) dto.target_date = input.targetDate;
  if (input.fundingType !== undefined) dto.funding_type = input.fundingType;
  if (input.fundingAmount !== undefined) {
    dto.funding_amount = input.fundingAmount?.toDecimalString() ?? null;
  }
  if (input.fundingSchedule !== undefined)
    dto.funding_schedule = input.fundingSchedule;
  if (input.recurrenceSchedule !== undefined)
    dto.recurrence_schedule = input.recurrenceSchedule;
  if (input.paused !== undefined) dto.paused = input.paused;
  return dto;
}

////////////////////////////////////////////////////////////////////////
//
// A create needs a name, an account and a target amount.
//
export type BudgetCreateInput = BudgetInput & {
  name: string;
  bankAccountId: string;
  targetBalance: Money;
};

export function budgetToCreateDto(input: BudgetCreateInput): BudgetCreateDto {
  return {
    ...budgetToUpdateDto(input),
    name: input.name,
    bank_account: input.bankAccountId,
    target_balance: input.targetBalance.toDecimalString(),
  };
}

////////////////////////////////////////////////////////////////////////
//
// Fill-up goals (type `A`) keyed by id, for attaching each to its
// recurring parent (`parent.fillupGoalId`).
//
export function fillupIndex(budgets: Iterable<Budget>): Map<string, Budget> {
  const map = new Map<string, Budget>();
  for (const b of budgets) {
    if (b.budgetType === "A") map.set(b.id, b);
  }
  return map;
}

////////////////////////////////////////////////////////////////////////
//
// Budget names keyed by id, for rows that show where money went.
//
export function budgetNameIndex(
  budgets: Iterable<Budget>,
): Map<string, string> {
  const map = new Map<string, string>();
  for (const b of budgets) map.set(b.id, b.name);
  return map;
}

////////////////////////////////////////////////////////////////////////
//
// Budgets a user can pick as an allocation target or transfer
// counterpart: not the account's Unallocated budget, not a fill-up
// goal, not archived.
//
export function isAssignableBudget(
  budget: Budget,
  unallocatedBudgetId: string | null,
): boolean {
  return (
    budget.id !== unallocatedBudgetId &&
    budget.budgetType !== "A" &&
    !budget.archived
  );
}
