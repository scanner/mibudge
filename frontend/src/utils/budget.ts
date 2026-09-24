//
// Budget presentation helpers for components that render the `Budget`
// DTO.  Each converts the DTO to `BudgetFigures` and applies the rules
// in `domain/budgetStatus`.
//

// app imports
//
import * as rules from "@/domain/budgetStatus";
import type { BudgetFigures, BudgetStatus, ProgressTone } from "@/domain/budgetStatus";
import { toLocalDate } from "@/domain/dates";
import { Money } from "@/domain/money";
import type { Budget } from "@/types/api";

////////////////////////////////////////////////////////////////////////
//
export function budgetFigures(budget: Budget): BudgetFigures {
  return {
    budgetType: budget.budget_type,
    balance: Money.of(budget.balance, budget.balance_currency),
    targetBalance: Money.ofNullable(budget.target_balance, budget.target_balance_currency),
    paused: budget.paused,
    complete: budget.complete,
    fundingPace: budget.funding_pace,
    targetDate: toLocalDate(budget.target_date),
    recurrenceSchedule: budget.recurrence_schedule,
    nextRecurrence: toLocalDate(budget.next_recurrence),
  };
}

////////////////////////////////////////////////////////////////////////
//
export function budgetProgress(budget: Budget): number {
  return rules.budgetProgress(budgetFigures(budget));
}

export function budgetStatus(budget: Budget): BudgetStatus {
  return rules.budgetStatus(budgetFigures(budget));
}

export function progressTone(status: BudgetStatus): ProgressTone {
  return rules.progressTone(status);
}

export function budgetMeta(budget: Budget): string {
  return rules.budgetMeta(budgetFigures(budget));
}
