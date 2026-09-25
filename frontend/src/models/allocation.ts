//
// Transaction allocations: the part of a transaction's amount assigned
// to a budget.  Model layer: domain type and DTO mapper for
// `/api/v1/allocations/`, plus pure helpers over allocation lists.
//

// app imports
//
import type { AllocationDto } from "@/api/dto";
import { DEFAULT_CURRENCY, Money, sumMoney } from "@/domain/money";

////////////////////////////////////////////////////////////////////////
//
export interface Allocation {
  id: string;
  transactionId: string;
  // `null` or the account's Unallocated budget when not yet assigned.
  budgetId: string | null;
  amount: Money;
  // The budget's balance right after this allocation.
  budgetBalance: Money;
  categoryId: string | null;
  categoryFullName: string | null;
  memo: string | null;
  createdAt: string;
}

////////////////////////////////////////////////////////////////////////
//
export function allocationFromDto(dto: AllocationDto): Allocation {
  const currency = dto.amount_currency || DEFAULT_CURRENCY;
  return {
    id: dto.id,
    transactionId: dto.transaction,
    budgetId: dto.budget ?? null,
    amount: Money.of(dto.amount, currency),
    budgetBalance: Money.of(
      dto.budget_balance,
      dto.budget_balance_currency || currency,
    ),
    categoryId: dto.category ?? null,
    categoryFullName: dto.category_full_name ?? null,
    memo: dto.memo ?? null,
    createdAt: dto.created_at,
  };
}

////////////////////////////////////////////////////////////////////////
//
// Allocations grouped by transaction id, in list order.
//
export function indexByTransaction(
  allocations: Iterable<Allocation>,
): Map<string, Allocation[]> {
  const map = new Map<string, Allocation[]>();
  for (const a of allocations) {
    const list = map.get(a.transactionId);
    if (list) list.push(a);
    else map.set(a.transactionId, [a]);
  }
  return map;
}

////////////////////////////////////////////////////////////////////////
//
// True when nothing is assigned to a real budget: no allocations, or
// all of them on Unallocated / no budget.  Callers that have not loaded
// a transaction's allocations must not ask.
//
export function isUnallocated(
  allocations: Allocation[],
  unallocatedBudgetId: string | null,
): boolean {
  if (allocations.length === 0) return true;
  return allocations.every(
    (a) => a.budgetId === null || a.budgetId === unallocatedBudgetId,
  );
}

////////////////////////////////////////////////////////////////////////
//
// Allocations to real budgets (not Unallocated).
//
export function assignedAllocations(
  allocations: Allocation[],
  unallocatedBudgetId: string | null,
): Allocation[] {
  return allocations.filter(
    (a) => a.budgetId !== null && a.budgetId !== unallocatedBudgetId,
  );
}

////////////////////////////////////////////////////////////////////////
//
// The splits body for `POST /transactions/<id>/splits/`: budget id →
// positive two-decimal amount, for every assigned allocation.
//
export function splitsOf(allocations: Allocation[]): Record<string, string> {
  const splits: Record<string, string> = {};
  for (const a of allocations) {
    if (a.budgetId) splits[a.budgetId] = a.amount.abs().toDecimalString();
  }
  return splits;
}

////////////////////////////////////////////////////////////////////////
//
// How much of `total` the given allocations cover, as the transaction
// detail's status line: fully allocated, the unassigned remainder, or
// the over-allocation.
//
export type AllocationCoverage =
  | { kind: "full"; amount: Money }
  | { kind: "remaining"; amount: Money }
  | { kind: "over"; amount: Money };

export function allocationCoverage(
  total: Money,
  allocations: Allocation[],
): AllocationCoverage {
  const txAmount = total.abs();
  const allocated = sumMoney(
    allocations.map((a) => a.amount.abs()),
    total.currency,
  );
  const diff = txAmount.minus(allocated);
  if (allocations.length > 0 && diff.isZero())
    return { kind: "full", amount: txAmount };
  if (diff.isPositive() || diff.isZero())
    return { kind: "remaining", amount: diff };
  return { kind: "over", amount: diff.abs() };
}
