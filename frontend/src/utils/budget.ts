//
// Budget domain helpers: status chip value, progress percentage,
// one-line meta text, and next funding amount.  All derived from the
// Budget object alone.
//

// app imports
//
import type { Budget } from "@/types/api";
import type { BudgetStatus } from "@/components/shared/StatusChip.vue";
import type { ProgressTone } from "@/components/shared/ProgressBar.vue";
import { rruleHuman } from "@/utils/rrule";

////////////////////////////////////////////////////////////////////////
//
// Parse a date-only string ("2026-08-01") as a local-time date.
// new Date("2026-08-01") parses as UTC midnight which shifts
// backward a day in western timezones.
//
export function parseLocalDate(s: string): Date {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
}

////////////////////////////////////////////////////////////////////////
//
// Progress as 0–100.  When there is no target, a funded budget is 100%.
//
export function budgetProgress(budget: Budget): number {
  const target = parseFloat(budget.target_balance ?? "0");
  if (target <= 0) return 100;
  const balance = parseFloat(budget.balance);
  return Math.max(0, (balance / target) * 100);
}

////////////////////////////////////////////////////////////////////////
//
export function budgetStatus(budget: Budget): BudgetStatus {
  if (budget.paused) return "paused";

  const balance = parseFloat(budget.balance);
  const target = parseFloat(budget.target_balance ?? "0");

  if (balance < 0) return "over";
  if (budget.complete) return "funded";
  if (target > 0 && balance >= target) return "funded";

  // Behind-pace is computed server-side (funded_amount vs funding
  // events elapsed on the schedule); the UI only presents it.
  if (budget.funding_pace === "behind") return "warn";

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
// One-line description for budget cards and the detail hero.
//
export function budgetMeta(budget: Budget): string {
  if (budget.budget_type === "G") {
    if (budget.target_date) {
      const d = parseLocalDate(budget.target_date);
      const label = d.toLocaleDateString(undefined, { month: "short", year: "numeric" });
      return `Goal · by ${label}`;
    }
    return "Goal";
  }
  if (budget.budget_type === "C") {
    return "Capped";
  }
  if (budget.recurrence_schedule) {
    let meta = `Recurring · refreshes ${rruleHuman(budget.recurrence_schedule)}`;
    if (budget.next_recurrence) {
      const label = parseLocalDate(budget.next_recurrence).toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
      });
      meta += ` · next refresh ${label}`;
    }
    return meta;
  }
  return "Recurring";
}
