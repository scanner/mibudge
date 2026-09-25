//
// Transaction and allocation model tests (`src/models/transaction.ts`,
// `src/models/allocation.ts`, `src/models/listRow.ts`,
// `src/models/internalTransaction.ts`).
//

// 3rd party imports
//
import { describe, expect, it } from "vitest";

// app imports
//
import { Money } from "@/domain/money";
import {
  allocationCoverage,
  allocationFromDto,
  assignedAllocations,
  indexByTransaction,
  isUnallocated,
  splitsOf,
} from "@/models/allocation";
import {
  amountRelativeTo,
  internalTransactionFromDto,
  transferToCreateDto,
} from "@/models/internalTransaction";
import { listRows, rowInstant, rowKey } from "@/models/listRow";
import {
  compareNewestFirst,
  displayName,
  occurredAt,
  transactionFromDto,
  transactionToUpdateDto,
} from "@/models/transaction";
import { makeAllocation, makeInternalTransaction, makeTransaction } from "../mocks/factories";

////////////////////////////////////////////////////////////////////////
//
describe("transactionFromDto", () => {
  // GIVEN: a transaction as the API sends it, with merchant details
  // WHEN:  it is mapped to the model
  // THEN:  amounts become Money, merchant fields are grouped, and the
  //        fields the schema marks non-null but the server may omit
  //        become null
  //
  it("maps every field", () => {
    const dto = makeTransaction({
      amount: "-12.34",
      amount_currency: "USD",
      merchant_name: "Blue Bottle",
      merchant_city: "Oakland",
      description_user_edited: true,
      has_details: true,
      transaction_date: null,
    });

    const tx = transactionFromDto(dto);

    expect(tx.amount.toString()).toBe("-12.34 USD");
    expect(tx.merchant.name).toBe("Blue Bottle");
    expect(tx.merchant.city).toBe("Oakland");
    expect(tx.descriptionUserEdited).toBe(true);
    expect(tx.hasDetails).toBe(true);
    expect(tx.linkedTransactionId).toBeNull();
    expect(tx.transactionDate).toBeNull();
    expect(tx.accountAvailableBalance.toString()).toBe("987.66 USD");
  });

  // GIVEN: a transaction with or without a transaction date
  // WHEN:  the instant it happened is taken
  // THEN:  the transaction date wins and the posted date fills in
  //
  it("falls back to the posted date", () => {
    expect(occurredAt({ transactionDate: "2026-01-02T00:00:00Z", postedDate: "p" })).toBe(
      "2026-01-02T00:00:00Z",
    );
    expect(occurredAt({ transactionDate: null, postedDate: "2026-01-03T00:00:00Z" })).toBe(
      "2026-01-03T00:00:00Z",
    );
  });

  // GIVEN: a transaction's party, description and raw description
  // WHEN:  its display name is taken
  // THEN:  the first non-empty one wins
  //
  it.each([
    [{ party: "Party", description: "D", rawDescription: "R" }, "Party"],
    [{ party: null, description: "D", rawDescription: "R" }, "D"],
    [{ party: "", description: "", rawDescription: "R" }, "R"],
  ])("displayName(%j) = %s", (fields, name) => {
    expect(displayName(fields)).toBe(name);
  });

  // GIVEN: transactions on different and equal dates
  // WHEN:  they are sorted newest first
  // THEN:  later dates come first, then later creation
  //
  it("sorts newest first", () => {
    const a = transactionFromDto(
      makeTransaction({
        transaction_date: "2026-01-01T00:00:00Z",
        created_at: "2026-01-05T00:00:00Z",
      }),
    );
    const b = transactionFromDto(
      makeTransaction({
        transaction_date: "2026-01-02T00:00:00Z",
        created_at: "2026-01-01T00:00:00Z",
      }),
    );
    const c = transactionFromDto(
      makeTransaction({
        transaction_date: "2026-01-01T00:00:00Z",
        created_at: "2026-01-06T00:00:00Z",
      }),
    );
    expect([a, b, c].sort(compareNewestFirst).map((t) => t.id)).toEqual([b.id, c.id, a.id]);
  });

  // GIVEN: a text edit, including clearing the memo
  // WHEN:  it becomes a PATCH body
  // THEN:  a cleared memo is sent as null so the server clears it
  //
  it.each([
    [{ memo: "" }, { memo: null }],
    [{ memo: "note" }, { memo: "note" }],
    [{ description: "Lunch" }, { description: "Lunch" }],
    [{}, {}],
  ])("transactionToUpdateDto(%j) = %j", (update, dto) => {
    expect(transactionToUpdateDto(update)).toEqual(dto);
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("allocations", () => {
  const UNALLOC = "unalloc";

  // GIVEN: allocations of several transactions
  // WHEN:  they are indexed by transaction
  // THEN:  each transaction lists its allocations in order
  //
  it("indexes by transaction", () => {
    const [a1, a2, b1] = [
      allocationFromDto(makeAllocation({ transaction: "a" })),
      allocationFromDto(makeAllocation({ transaction: "a" })),
      allocationFromDto(makeAllocation({ transaction: "b" })),
    ];
    const index = indexByTransaction([a1, b1, a2]);
    expect(index.get("a")).toEqual([a1, a2]);
    expect(index.get("b")).toEqual([b1]);
  });

  // GIVEN: a transaction's allocations
  // WHEN:  it is checked for being unallocated
  // THEN:  none, or only Unallocated / no-budget legs, count as unallocated
  //
  it.each([
    [undefined, true],
    [[], true],
    [[{ budget: UNALLOC }], true],
    [[{ budget: null }], true],
    [[{ budget: UNALLOC }, { budget: "rent" }], false],
  ])("isUnallocated(%j) = %s", (legs, expected) => {
    const allocs = legs?.map((l) => allocationFromDto(makeAllocation(l)));
    expect(isUnallocated(allocs, UNALLOC)).toBe(expected);
  });

  // GIVEN: a 30.00 debit with assigned and unallocated legs
  // WHEN:  the assigned legs, the splits body and the coverage are taken
  // THEN:  Unallocated is excluded, amounts are positive two-decimal
  //        strings, and coverage reports the remainder
  //
  it("builds splits and coverage from assigned legs", () => {
    const allocs = [
      allocationFromDto(makeAllocation({ budget: "rent", amount: "-10.00" })),
      allocationFromDto(makeAllocation({ budget: "food", amount: "-5.5" })),
      allocationFromDto(makeAllocation({ budget: UNALLOC, amount: "-14.50" })),
    ];
    const assigned = assignedAllocations(allocs, UNALLOC);
    expect(assigned).toHaveLength(2);
    expect(splitsOf(assigned)).toEqual({ rent: "10.00", food: "5.50" });

    const total = Money.of("-30.00");
    const remaining = allocationCoverage(total, assigned);
    expect(remaining.kind).toBe("remaining");
    expect(remaining.amount.toDecimalString()).toBe("14.50");
  });

  // GIVEN: legs that exactly cover, or exceed, the transaction
  // WHEN:  coverage is computed
  // THEN:  it is "full" with the total, or "over" with the excess
  //
  it("reports full and over coverage", () => {
    const leg = (amount: string) => allocationFromDto(makeAllocation({ budget: "x", amount }));
    const full = allocationCoverage(Money.of("-10"), [leg("-4"), leg("-6")]);
    expect([full.kind, full.amount.toDecimalString()]).toEqual(["full", "10.00"]);
    const over = allocationCoverage(Money.of("-10"), [leg("-8"), leg("-4")]);
    expect([over.kind, over.amount.toDecimalString()]).toEqual(["over", "2.00"]);
    expect(allocationCoverage(Money.of("-10"), []).kind).toBe("remaining");
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("internal transactions and list rows", () => {
  // GIVEN: a transfer from budget A to budget B
  // WHEN:  its amount is read from each side
  // THEN:  B sees it positive, A negative
  //
  it("signs the amount relative to a budget", () => {
    const itx = internalTransactionFromDto(
      makeInternalTransaction({ src_budget: "A", dst_budget: "B", amount: "25.00" }),
    );
    expect(amountRelativeTo(itx, "B").toDecimalString()).toBe("25.00");
    expect(amountRelativeTo(itx, "A").toDecimalString()).toBe("-25.00");
    expect(
      transferToCreateDto({
        bankAccountId: "acct",
        srcBudgetId: "A",
        dstBudgetId: "B",
        amount: Money.of("-3"),
      }),
    ).toEqual({ bank_account: "acct", src_budget: "A", dst_budget: "B", amount: "3.00" });
  });

  // GIVEN: transactions and, optionally, transfers
  // WHEN:  list rows are built
  // THEN:  transfers are appended only when given, and each row has a
  //        kind-unique key and an instant
  //
  it("merges transactions and transfers", () => {
    const tx = transactionFromDto(makeTransaction({ transaction_date: "2026-01-02T00:00:00Z" }));
    const itx = internalTransactionFromDto(
      makeInternalTransaction({ effective_date: "2026-01-03T00:00:00Z" }),
    );
    expect(listRows([tx], null)).toHaveLength(1);
    const rows = listRows([tx], [itx]);
    expect(rows.map(rowKey)).toEqual([`tx${tx.id}`, `itx${itx.id}`]);
    expect(rows.map(rowInstant)).toEqual(["2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z"]);
  });
});
