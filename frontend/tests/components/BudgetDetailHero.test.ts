//
// BudgetDetailHero tests: the goal's date axis renders calendar dates
// without a timezone shift.
//

// 3rd party imports
//
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

// app imports
//
import BudgetDetailHero from "@/components/budgets/BudgetDetailHero.vue";
import { budgetFromDto } from "@/models/budget";
import { makeBudget } from "../mocks/factories";

////////////////////////////////////////////////////////////////////////
//
describe("BudgetDetailHero", () => {
  // GIVEN: a goal budget with target date 2026-08-01, viewed in a
  //        browser west of UTC (the suite runs in America/New_York)
  // WHEN:  the hero renders its date axis
  // THEN:  the end label reads "Aug 1, 2026", not the day before
  //
  it("shows the target date without a UTC shift", () => {
    const budget = budgetFromDto(
      makeBudget({ budget_type: "G", target_date: "2026-08-01" }),
    );

    const wrapper = mount(BudgetDetailHero, { props: { budget } });

    expect(wrapper.text()).toContain("Aug 1, 2026");
    expect(wrapper.text()).not.toContain("Jul 31, 2026");
  });

  // GIVEN: a budget of each type
  // WHEN:  the hero renders
  // THEN:  the type chip names the type
  //
  it.each([
    ["G", "Goal"],
    ["R", "Recurring"],
    ["A", "Fill-up"],
    ["C", "Capped"],
  ] as const)("labels type %s as %s", (budget_type, label) => {
    const budget = budgetFromDto(makeBudget({ budget_type }));
    const wrapper = mount(BudgetDetailHero, { props: { budget } });
    expect(wrapper.text()).toContain(label);
  });
});
