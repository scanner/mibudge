//
// Budgets store tests: the id-keyed cache, its loaders, and the
// mutations that keep it current.
//

// 3rd party imports
//
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

// app imports
//
import { Money } from "@/domain/money";
import { budgetFromDto } from "@/models/budget";
import { useBudgetsStore } from "@/stores/budgets";
import { withAuth } from "../helpers";
import { makeBudget, makePage } from "../mocks/factories";
import { lastRequest, requestsTo, server } from "../mocks/server";

////////////////////////////////////////////////////////////////////////
//
describe("upsert", () => {
  // GIVEN: an empty cache
  // WHEN:  a budget is upserted, then upserted again with changes
  // THEN:  it is retrievable by id and the later version replaces the first
  //
  it("inserts and replaces by id", () => {
    const store = useBudgetsStore();
    const budget = budgetFromDto(makeBudget({ name: "Rent" }));

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
  it("reset empties the cache", () => {
    const store = useBudgetsStore();
    store.upsert(budgetFromDto(makeBudget()));
    store.reset();
    expect(store.all).toEqual([]);
  });

  // GIVEN: cached budgets
  // WHEN:  some or all are invalidated
  // THEN:  those entries are dropped
  //
  it("invalidate drops entries", () => {
    const store = useBudgetsStore();
    const [a, b] = [budgetFromDto(makeBudget()), budgetFromDto(makeBudget())];
    store.upsert(a);
    store.upsert(b);
    store.invalidate([a.id]);
    expect(store.all).toEqual([b]);
    store.invalidate();
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

    expect(result).toEqual(budgetFromDto(budget));
    expect(store.byId(budget.id)).toEqual(budgetFromDto(budget));
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

    expect(result).toEqual(budgets.map(budgetFromDto));
    expect(store.all).toEqual(budgets.map(budgetFromDto));
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
    expect(store.error).toBe("Failed to load budgets. (HTTP 500)");
    expect(store.loading).toBe(false);
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("mutations", () => {
  // GIVEN: two budgets on the server
  // WHEN:  money is moved between them
  // THEN:  the transfer is created and both budgets are refetched into
  //        the cache
  //
  it("transfer creates the transfer and refetches both budgets", async () => {
    withAuth();
    const store = useBudgetsStore();

    await store.transfer({
      bankAccountId: "acct",
      srcBudgetId: "src",
      dstBudgetId: "dst",
      amount: Money.of("25"),
    });

    const [post] = await requestsTo("POST", "/api/v1/internal-transactions/");
    expect(post.body).toEqual({
      bank_account: "acct",
      src_budget: "src",
      dst_budget: "dst",
      amount: "25.00",
    });
    expect(store.byId("src")).not.toBeNull();
    expect(store.byId("dst")).not.toBeNull();
  });

  // GIVEN: a budget
  // WHEN:  it is updated, and then archived
  // THEN:  the cache holds the server's answer, and archiving refetches
  //        the account's budgets (the balance moved to Unallocated)
  //
  it("update and archive keep the cache current", async () => {
    withAuth();
    const store = useBudgetsStore();

    const updated = await store.update("b1", { paused: true });
    expect(store.byId("b1")).toEqual(updated);
    expect(updated.paused).toBe(true);

    await store.archive("b1");
    expect(store.byId("b1")?.archived).toBe(true);
    expect(await requestsTo("GET", "/api/v1/budgets/")).toHaveLength(1);
  });

  // GIVEN: a new budget's fields
  // WHEN:  it is created
  // THEN:  it is cached and returned
  //
  it("create caches the new budget", async () => {
    withAuth();
    const store = useBudgetsStore();

    const created = await store.create({
      name: "Trip",
      bankAccountId: "acct",
      budgetType: "G",
      targetBalance: Money.of("2000"),
    });

    expect(store.byId(created.id)?.name).toBe("Trip");
    expect(store.forAccount("acct").map((b) => b.id)).toContain(created.id);
    expect(store.names.get(created.id)).toBe("Trip");
  });
});
