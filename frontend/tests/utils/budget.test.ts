//
// Budget domain helper tests: local-date parsing, progress, status,
// tone, and the one-line meta text.
//

// 3rd party imports
//
import { describe, expect, it, vi } from "vitest";

// app imports
//
import {
  budgetMeta,
  budgetProgress,
  budgetStatus,
  parseLocalDate,
  progressTone,
} from "@/utils/budget";
import type { Budget } from "@/types/api";
import { makeBudget } from "../mocks/factories";

////////////////////////////////////////////////////////////////////////
//
describe("parseLocalDate", () => {
  // GIVEN: a date-only string
  // WHEN:  it is parsed in a browser east or west of UTC
  // THEN:  the result is local midnight on that same calendar day
  //
  it.each(["Pacific/Honolulu", "America/New_York", "UTC", "Asia/Tokyo"])("in %s", (tz) => {
    // `vi.stubEnv` changes the process zone for this test only;
    // `unstubEnvs` in vitest.config.ts restores America/New_York.
    //
    vi.stubEnv("TZ", tz);
    expect(Intl.DateTimeFormat().resolvedOptions().timeZone).toBe(tz);
    const d = parseLocalDate("2026-08-01");
    expect([d.getFullYear(), d.getMonth(), d.getDate(), d.getHours()]).toEqual([2026, 7, 1, 0]);
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("budgetProgress", () => {
  // GIVEN: a budget's balance and target
  // WHEN:  progress is computed
  // THEN:  it is balance / target as a percentage, never below 0, and
  //        100 when there is no positive target
  //
  it.each([
    ["50.00", "200.00", 25],
    ["300.00", "200.00", 150],
    ["-10.00", "200.00", 0],
    ["10.00", "0.00", 100],
    ["10.00", null, 100],
  ])("balance %s / target %s → %d", (balance, target, expected) => {
    expect(budgetProgress(makeBudget({ balance, target_balance: target }))).toBe(expected);
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("budgetStatus / progressTone", () => {
  // GIVEN: a budget in a given state
  // WHEN:  its status chip and progress tone are derived
  // THEN:  paused wins, then overdrawn, then funded, then behind-pace
  //
  it.each<[string, Partial<Budget>, string, string]>([
    ["paused", { paused: true, balance: "-5.00" }, "paused", "neutral"],
    ["overdrawn", { balance: "-0.01" }, "over", "coral"],
    ["complete", { complete: true, balance: "1.00" }, "funded", "mint"],
    ["at target", { balance: "500.00", target_balance: "500.00" }, "funded", "mint"],
    ["behind pace", { funding_pace: "behind" }, "warn", "amber"],
    ["in progress", {}, "progress", "ocean"],
  ])("%s", (_label, overrides, status, tone) => {
    const s = budgetStatus(makeBudget(overrides));
    expect(s).toBe(status);
    expect(progressTone(s)).toBe(tone);
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("budgetMeta", () => {
  // GIVEN: a budget of a given type and schedule
  // WHEN:  its one-line meta text is built
  // THEN:  it names the type, and for goals the target month, and for
  //        recurring budgets the refresh schedule and next refresh date
  //
  it.each<[string, Partial<Budget>, string]>([
    ["goal with date", { budget_type: "G", target_date: "2026-08-01" }, "Goal · by Aug 2026"],
    ["goal without date", { budget_type: "G", target_date: null }, "Goal"],
    ["capped", { budget_type: "C" }, "Capped"],
    ["recurring without schedule", { budget_type: "R", recurrence_schedule: null }, "Recurring"],
    [
      "recurring",
      { budget_type: "R", recurrence_schedule: "RRULE:FREQ=MONTHLY;BYMONTHDAY=1" },
      "Recurring · refreshes Every month on the 1st",
    ],
    [
      "recurring with next refresh",
      {
        budget_type: "R",
        recurrence_schedule: "RRULE:FREQ=MONTHLY;BYMONTHDAY=1",
        next_recurrence: "2026-10-01",
      },
      "Recurring · refreshes Every month on the 1st · next refresh Oct 1, 2026",
    ],
  ])("%s", (_label, overrides, expected) => {
    expect(budgetMeta(makeBudget(overrides))).toBe(expected);
  });
});
