//
// Transaction navigation store tests: prev/next lookup over the saved
// list order.
//

// 3rd party imports
//
import { describe, expect, it } from "vitest";

// app imports
//
import { useTransactionNavStore } from "@/stores/transactionNav";

////////////////////////////////////////////////////////////////////////
//
describe("prevId / nextId", () => {
  // GIVEN: the ordered ids from the last transaction list
  // WHEN:  the neighbours of an id are looked up
  // THEN:  the adjacent ids are returned, or null at either end and for
  //        an id not in the list
  //
  it.each([
    ["a", null, "b"],
    ["b", "a", "c"],
    ["c", "b", null],
    ["zzz", null, null],
  ])("neighbours of %s are %s / %s", (id, prev, next) => {
    const nav = useTransactionNavStore();
    nav.setIds(["a", "b", "c"]);
    expect(nav.prevId(id)).toBe(prev);
    expect(nav.nextId(id)).toBe(next);
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("reset", () => {
  // GIVEN: saved ids, search and filter
  // WHEN:  the store is reset
  // THEN:  all three are cleared
  //
  it("clears everything", () => {
    const nav = useTransactionNavStore();
    nav.setIds(["a"]);
    nav.savedSearch = "x";
    nav.savedFilter = "pending";
    nav.reset();
    expect([nav.orderedIds, nav.savedSearch, nav.savedFilter]).toEqual([
      [],
      "",
      "",
    ]);
  });
});
