//
// Budget model tests (`src/models/budget.ts`): DTO → model, model →
// create / update DTO, and the list helpers.
//

// 3rd party imports
//
import { describe, expect, it } from "vitest";

// app imports
//
import type { LocalDate } from "@/domain/dates";
import { Money } from "@/domain/money";
import {
  budgetFromDto,
  budgetNameIndex,
  budgetToCreateDto,
  budgetToUpdateDto,
  fillupIndex,
  isAssignableBudget,
} from "@/models/budget";
import { makeBudget } from "../mocks/factories";

////////////////////////////////////////////////////////////////////////
//
describe("budgetFromDto", () => {
  // GIVEN: a budget as the API sends it
  // WHEN:  it is mapped to the model
  // THEN:  money fields become Money in their currencies, date-only
  //        fields become calendar dates, and absent values are null
  //
  it("maps every field", () => {
    const dto = makeBudget({
      name: "Rent",
      budget_type: "R",
      balance: "-12.50",
      balance_currency: "EUR",
      target_balance: "1500.00",
      target_balance_currency: "EUR",
      funding_amount: null,
      target_date: "2026-08-01",
      next_recurrence: "2026-10-01",
      fillup_goal: "fill-1",
      funding_pace: "behind",
      next_funding: {
        date: "2026-09-30",
        amount: "40.00",
        amount_currency: "EUR",
      },
    });

    const b = budgetFromDto(dto);

    expect(b.id).toBe(dto.id);
    expect(b.bankAccountId).toBe(dto.bank_account);
    expect(b.budgetType).toBe("R");
    expect(b.balance.toString()).toBe("-12.50 EUR");
    expect(b.targetBalance?.toString()).toBe("1500.00 EUR");
    expect(b.fundingAmount).toBeNull();
    expect(b.targetDate).toBe("2026-08-01");
    expect(b.nextRecurrence).toBe("2026-10-01");
    expect(b.fillupGoalId).toBe("fill-1");
    expect(b.fundingPace).toBe("behind");
    expect(b.nextFunding?.date).toBe("2026-09-30");
    expect(b.nextFunding?.amount.toString()).toBe("40.00 EUR");
    expect(b.archivedAt).toBeNull();
  });

  // GIVEN: a `next_funding` object that is missing or malformed
  // WHEN:  the budget is mapped
  // THEN:  `nextFunding` is null rather than a half-filled value
  //
  it.each([
    [null],
    [{ date: "not-a-date", amount: "1.00" }],
    [{ date: "2026-09-30" }],
  ])("drops next_funding %j", (next_funding) => {
    expect(budgetFromDto(makeBudget({ next_funding })).nextFunding).toBeNull();
  });

  // GIVEN: a budget with blank schedules
  // WHEN:  it is mapped
  // THEN:  the schedules are null
  //
  it("treats blank schedules as absent", () => {
    const b = budgetFromDto(
      makeBudget({ funding_schedule: "", recurrence_schedule: "" }),
    );
    expect(b.fundingSchedule).toBeNull();
    expect(b.recurrenceSchedule).toBeNull();
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("budgetToUpdateDto / budgetToCreateDto", () => {
  // GIVEN: an edit to some budget fields
  // WHEN:  it becomes a PATCH body
  // THEN:  only the given fields are sent, as API strings; `null`
  //        clears a nullable field
  //
  it("sends only the given fields", () => {
    expect(
      budgetToUpdateDto({
        name: "Rent",
        targetBalance: Money.of("1500"),
        targetDate: null,
        fundingAmount: null,
        paused: true,
      }),
    ).toEqual({
      name: "Rent",
      target_balance: "1500.00",
      target_date: null,
      funding_amount: null,
      paused: true,
    });
    expect(budgetToUpdateDto({})).toEqual({});
  });

  // GIVEN: a new budget with no target
  // WHEN:  it becomes a POST body
  // THEN:  the name, account, type and target are sent
  //
  it("fills the create-only fields", () => {
    expect(
      budgetToCreateDto({
        name: "Trip",
        bankAccountId: "acct",
        budgetType: "G",
        targetBalance: Money.of("2000"),
        targetDate: "2027-01-01" as LocalDate,
        fundingType: "D",
        fundingSchedule: "RRULE:FREQ=MONTHLY",
      }),
    ).toEqual({
      name: "Trip",
      bank_account: "acct",
      budget_type: "G",
      target_balance: "2000.00",
      target_date: "2027-01-01",
      funding_type: "D",
      funding_schedule: "RRULE:FREQ=MONTHLY",
    });
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("list helpers", () => {
  // GIVEN: budgets of every type, one archived, one the Unallocated budget
  // WHEN:  the list helpers run
  // THEN:  fill-ups are indexed by id, names by id, and only live
  //        user budgets are assignable
  //
  it("indexes fill-ups and names, and filters assignable budgets", () => {
    const [goal, fill, archived, unalloc] = [
      budgetFromDto(makeBudget({ name: "Goal", budget_type: "G" })),
      budgetFromDto(makeBudget({ name: "Fill", budget_type: "A" })),
      budgetFromDto(makeBudget({ name: "Old", archived: true })),
      budgetFromDto(makeBudget({ name: "Unallocated" })),
    ];
    const all = [goal, fill, archived, unalloc];

    expect([...fillupIndex(all).keys()]).toEqual([fill.id]);
    expect(budgetNameIndex(all).get(goal.id)).toBe("Goal");
    expect(all.filter((b) => isAssignableBudget(b, unalloc.id))).toEqual([
      goal,
    ]);
  });
});
