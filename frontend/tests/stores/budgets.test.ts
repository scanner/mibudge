//
// Budgets store tests: the id-keyed cache and its loaders.
//

// 3rd party imports
//
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

// app imports
//
import { useBudgetsStore } from "@/stores/budgets";
import { withAuth } from "../helpers";
import { makeBudget, makePage } from "../mocks/factories";
import { lastRequest, server } from "../mocks/server";

////////////////////////////////////////////////////////////////////////
//
describe("upsert", () => {
  // GIVEN: an empty cache
  // WHEN:  a budget is upserted, then upserted again with changes
  // THEN:  it is retrievable by id and the later version replaces the first
  //
  it("inserts and replaces by id", () => {
    const store = useBudgetsStore();
    const budget = makeBudget({ name: "Rent" });

    store.upsert(budget);
    store.upsert({ ...budget, name: "Mortgage" });

    expect(store.byId(budget.id)?.name).toBe("Mortgage");
    expect(store.all).toHaveLength(1);
    expect(store.byId("missing")).toBeNull();
  });

  // GIVEN: a cache holding budgets
  // WHEN:  it is cleared
  // THEN:  no budgets remain
  //
  it("clear empties the cache", () => {
    const store = useBudgetsStore();
    store.upsert(makeBudget());
    store.clear();
    expect(store.all).toEqual([]);
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("fetchOne", () => {
  // GIVEN: a budget on the server
  // WHEN:  it is fetched by id
  // THEN:  `GET /budgets/<id>/` is sent, the budget is returned and cached
  //
  it("fetches and caches a budget", async () => {
    withAuth();
    const budget = makeBudget({ name: "Travel" });
    server.use(http.get(`/api/v1/budgets/${budget.id}/`, () => HttpResponse.json(budget)));
    const store = useBudgetsStore();

    const result = await store.fetchOne(budget.id);

    expect(result).toEqual(budget);
    expect(store.byId(budget.id)).toEqual(budget);
    expect((await lastRequest())?.path).toBe(`/api/v1/budgets/${budget.id}/`);
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("fetchList", () => {
  // GIVEN: budgets on the server
  // WHEN:  a filtered list is fetched
  // THEN:  the filters are sent as query parameters
  //  AND:  the results are returned and cached, and loading ends
  //
  it("fetches with filters and caches the results", async () => {
    withAuth();
    const budgets = [makeBudget({ name: "A" }), makeBudget({ name: "B" })];
    server.use(http.get("/api/v1/budgets/", () => HttpResponse.json(makePage(budgets))));
    const store = useBudgetsStore();

    const result = await store.fetchList({ bank_account: "acct-1", archived: false });

    expect(result).toEqual(budgets);
    expect(store.all).toEqual(budgets);
    expect(store.loading).toBe(false);
    expect(store.error).toBeNull();
    expect((await lastRequest())?.path).toBe("/api/v1/budgets/?bank_account=acct-1&archived=false");
  });

  // GIVEN: a budget list request that fails
  // WHEN:  the list is fetched
  // THEN:  the call rejects, `error` holds the message, and loading ends
  //
  it("records the error and rethrows", async () => {
    withAuth();
    server.use(http.get("/api/v1/budgets/", () => new HttpResponse(null, { status: 500 })));
    const store = useBudgetsStore();

    await expect(store.fetchList()).rejects.toMatchObject({ status: 500 });
    expect(store.error).toBe("HTTP 500");
    expect(store.loading).toBe(false);
  });
});
