//
// Label tests (`src/domain/labels.ts`): account, budget and
// transaction type labels and their fallbacks.
//

// 3rd party imports
//
import { describe, expect, it } from "vitest";

// app imports
//
import {
  accountTypeLabel,
  accountTypeMeta,
  BUDGET_TYPE_LABELS,
  transactionTypeLabel,
} from "@/domain/labels";

////////////////////////////////////////////////////////////////////////
//
describe("account type labels", () => {
  // GIVEN: an account type code and an optional account number
  // WHEN:  the label and the meta line are built
  // THEN:  known codes are named, unknown codes pass through, and the
  //        meta line appends the last four digits
  //
  it.each([
    ["C", null, "Checking", "Checking"],
    ["S", "12345678", "Savings", "Savings ····5678"],
    ["X", "99", "Credit card", "Credit card ····99"],
    ["Z", null, "Z", "Z"],
  ])("%s / %j", (type, number, label, meta) => {
    expect(accountTypeLabel(type)).toBe(label);
    expect(accountTypeMeta(type, number)).toBe(meta);
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("budget type labels", () => {
  // GIVEN: each budget type code
  // WHEN:  its label is looked up
  // THEN:  it has a display name
  //
  it("names every type", () => {
    expect(BUDGET_TYPE_LABELS).toEqual({
      G: "Goal",
      R: "Recurring",
      A: "Fill-up",
      C: "Capped",
    });
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("transactionTypeLabel", () => {
  // GIVEN: a transaction type from the API
  // WHEN:  its label is looked up
  // THEN:  known types are named, blank is empty, unknown passes through
  //
  it.each([
    ["ach", "ACH transfer"],
    ["round-up_transfer", "Round-up transfer"],
    ["", ""],
    [null, ""],
    ["brand_new_type", "brand_new_type"],
  ])("%j → %j", (type, label) => {
    expect(transactionTypeLabel(type)).toBe(label);
  });
});
