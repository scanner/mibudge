//
// Budget presentation rules: the status chip, the progress percentage
// and its colour tone, and the one-line meta text.  Domain layer: pure
// TypeScript over the `BudgetFigures` a budget model provides.
//
// `BudgetStatus` and `ProgressTone` are the value types the
// `StatusChip` and `ProgressBar` components render.
//

// app imports
//
import type { LocalDate } from "@/domain/dates";
import { formatLocalDate } from "@/domain/dates";
import type { BudgetType, FundingPace } from "@/domain/labels";
import type { Money } from "@/domain/money";
import { rruleHuman } from "@/domain/rrule";

////////////////////////////////////////////////////////////////////////
//
export type BudgetStatus = "funded" | "progress" | "warn" | "over" | "paused";

export type ProgressTone = "mint" | "ocean" | "amber" | "coral" | "neutral";

////////////////////////////////////////////////////////////////////////
//
// The budget fields these rules read.  The `Budget` model satisfies it.
//
export interface BudgetFigures {
  budgetType: BudgetType;
  balance: Money;
  targetBalance: Money | null;
  paused: boolean;
  complete: boolean;
  fundingPace: FundingPace | null;
  targetDate: LocalDate | null;
  recurrenceSchedule: string | null;
  nextRecurrence: LocalDate | null;
}

////////////////////////////////////////////////////////////////////////
//
// Progress as a percentage of the target, never below 0 (it may exceed
// 100).  A budget with no positive target counts as 100%.
//
export function budgetProgress(
  budget: Pick<BudgetFigures, "balance" | "targetBalance">,
): number {
  const target = budget.targetBalance;
  if (!target || !target.isPositive()) return 100;
  const pct = budget.balance.amount
    .dividedBy(target.amount)
    .times(100)
    .toNumber();
  return Math.max(0, pct);
}

////////////////////////////////////////////////////////////////////////
//
// Paused wins, then overdrawn, then funded (complete or at target),
// then behind pace.  Pace is computed server-side (funded amount vs.
// funding events elapsed on the schedule); the SPA only presents it.
//
export function budgetStatus(
  budget: Pick<
    BudgetFigures,
    "paused" | "balance" | "targetBalance" | "complete" | "fundingPace"
  >,
): BudgetStatus {
  if (budget.paused) return "paused";
  if (budget.balance.isNegative()) return "over";
  if (budget.complete) return "funded";
  const target = budget.targetBalance;
  if (target && target.isPositive() && budget.balance.cmp(target) >= 0)
    return "funded";
  if (budget.fundingPace === "behind") return "warn";
  return "progress";
}

////////////////////////////////////////////////////////////////////////
//
export function progressTone(status: BudgetStatus): ProgressTone {
  switch (status) {
    case "funded":
      return "mint";
    case "warn":
      return "amber";
    case "over":
      return "coral";
    case "paused":
      return "neutral";
    default:
      return "ocean";
  }
}

////////////////////////////////////////////////////////////////////////
//
// One-line description for budget cards and the detail hero, e.g.
// `"Goal · by Aug 2026"` or
// `"Recurring · refreshes Every month on the 1st · next refresh Oct 1, 2026"`.
//
export function budgetMeta(budget: BudgetFigures, locale?: string): string {
  if (budget.budgetType === "G") {
    if (budget.targetDate) {
      const label = formatLocalDate(
        budget.targetDate,
        { month: "short", year: "numeric" },
        locale,
      );
      return `Goal · by ${label}`;
    }
    return "Goal";
  }
  if (budget.budgetType === "C") {
    return "Capped";
  }
  if (budget.recurrenceSchedule) {
    let meta = `Recurring · refreshes ${rruleHuman(budget.recurrenceSchedule)}`;
    if (budget.nextRecurrence) {
      const label = formatLocalDate(
        budget.nextRecurrence,
        { month: "short", day: "numeric", year: "numeric" },
        locale,
      );
      meta += ` · next refresh ${label}`;
    }
    return meta;
  }
  return "Recurring";
}
