//
// Bank-accounts store tests: the cached list and the mutations that
// keep it current.
//

// 3rd party imports
//
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

// app imports
//
import { Money } from "@/domain/money";
import { useBankAccountsStore } from "@/stores/bankAccounts";
import { withAuth } from "../helpers";
import { makeBankAccount, makePage } from "../mocks/factories";
import { requestsTo, server } from "../mocks/server";

////////////////////////////////////////////////////////////////////////
//
describe("bank accounts store", () => {
  // GIVEN: the user's accounts on the server
  // WHEN:  the list is loaded twice, then invalidated and loaded again
  // THEN:  it is fetched once until invalidated
  //
  it("loads once until invalidated", async () => {
    withAuth();
    const account = makeBankAccount({ name: "Household" });
    server.use(http.get("/api/v1/bank-accounts/", () => HttpResponse.json(makePage([account]))));
    const store = useBankAccountsStore();

    await store.loadAll();
    await store.loadAll();
    expect(await requestsTo("GET", "/api/v1/bank-accounts/")).toHaveLength(1);
    expect(store.byId(account.id)?.name).toBe("Household");

    store.invalidate();
    await store.loadAll();
    expect(await requestsTo("GET", "/api/v1/bank-accounts/")).toHaveLength(2);
  });

  // GIVEN: a cached account
  // WHEN:  it is renamed, a new account is created, and one is removed
  // THEN:  the cache follows each change
  //
  it("create, update and remove keep the cache current", async () => {
    withAuth();
    const store = useBankAccountsStore();
    const existing = await store.fetchOne("a1");

    const renamed = await store.update(existing.id, { name: "Renamed" });
    expect(store.byId("a1")?.name).toBe("Renamed");
    expect(renamed.name).toBe("Renamed");

    const created = await store.create({
      accountType: "C",
      name: "New",
      bankId: "bank",
      currency: "USD",
      accountNumber: "1234",
      postedBalance: Money.of("10"),
      availableBalance: null,
    });
    expect(store.all.map((a) => a.id)).toEqual(["a1", created.id]);

    await store.remove("a1");
    expect(store.byId("a1")).toBeNull();
    expect(await requestsTo("DELETE", "/api/v1/bank-accounts/a1/")).toHaveLength(1);

    store.reset();
    expect(store.all).toEqual([]);
  });
});
