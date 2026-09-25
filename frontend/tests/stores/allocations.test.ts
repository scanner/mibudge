//
// Allocations store tests: the per-account allocation index, fetched
// once and updated in place after a split.
//

// 3rd party imports
//
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

// app imports
//
import { allocationFromDto } from "@/models/allocation";
import { useAllocationsStore } from "@/stores/allocations";
import { withAuth } from "../helpers";
import { makeAllocation, makePage } from "../mocks/factories";
import { requestsTo, server } from "../mocks/server";

////////////////////////////////////////////////////////////////////////
//
describe("allocations store", () => {
  // GIVEN: an account's allocations on the server, over two pages
  // WHEN:  the index is loaded by several callers, then again later
  // THEN:  the pages are fetched once and indexed by transaction
  //
  it("loads the account index once", async () => {
    withAuth();
    const [a, b] = [
      makeAllocation({ transaction: "t1" }),
      makeAllocation({ transaction: "t2" }),
    ];
    server.use(
      http.get("/api/v1/allocations/", ({ request }) =>
        new URL(request.url).searchParams.get("page") === "2"
          ? HttpResponse.json(makePage([b]))
          : HttpResponse.json(
              makePage([a], {
                next: "http://localhost/api/v1/allocations/?page=2",
              }),
            ),
      ),
    );
    const store = useAllocationsStore();

    const [index] = await Promise.all([
      store.loadForAccount("acct"),
      store.loadForAccount("acct"),
    ]);
    await store.loadForAccount("acct");

    expect([...index.keys()]).toEqual(["t1", "t2"]);
    expect(store.indexFor("acct")?.get("t2")).toEqual([allocationFromDto(b)]);
    expect(await requestsTo("GET", "/api/v1/allocations/")).toHaveLength(2);
  });

  // GIVEN: a loaded index
  // WHEN:  one transaction is re-split, and then the account invalidated
  // THEN:  that transaction's entries are replaced in place, and the
  //        index is dropped on invalidation
  //
  it("updates a transaction in place and invalidates", async () => {
    withAuth();
    const store = useAllocationsStore();
    await store.loadForAccount("acct");
    const replacement = [
      allocationFromDto(makeAllocation({ transaction: "t9" })),
    ];

    store.setForTransaction("acct", "t9", replacement);
    store.setForTransaction("other", "t9", replacement);

    expect(store.indexFor("acct")?.get("t9")).toEqual(replacement);
    expect(store.indexFor("other")).toBeNull();
    store.invalidate("acct");
    expect(store.indexFor("acct")).toBeNull();
  });

  // GIVEN: a loaded index being refetched
  // WHEN:  a transaction is re-split before the refetch answers, and the
  //        refetch answers with what the server had before the split
  // THEN:  the old index stays readable while the refetch runs
  //  AND:  the split survives the refetch's result
  //
  it("keeps a split made while a refetch is in flight", async () => {
    withAuth();
    const store = useAllocationsStore();
    const before = makeAllocation({ transaction: "t1" });
    server.use(
      http.get("/api/v1/allocations/", () =>
        HttpResponse.json(makePage([before])),
      ),
    );
    await store.loadForAccount("acct");

    // Hold the refetch until the split has been applied.
    let release!: () => void;
    const gate = new Promise<void>((resolve) => (release = resolve));
    server.use(
      http.get("/api/v1/allocations/", async () => {
        await gate;
        return HttpResponse.json(makePage([before]));
      }),
    );
    const refetch = store.loadForAccount("acct", true);
    expect(store.indexFor("acct")?.get("t1")).toEqual([
      allocationFromDto(before),
    ]);

    const split = [
      allocationFromDto(makeAllocation({ transaction: "t1", budget: "rent" })),
    ];
    store.setForTransaction("acct", "t1", split);
    release();
    await refetch;

    expect(store.indexFor("acct")?.get("t1")).toEqual(split);
  });
});
