//
// Bank-accounts store tests: the cached list and the mutations that
// keep it current.
//

// 3rd party imports
//
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

// app imports
//
import { Money } from "@/domain/money";
import { bankAccountFromDto } from "@/models/bankAccount";
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
    server.use(
      http.get("/api/v1/bank-accounts/", () =>
        HttpResponse.json(makePage([account])),
      ),
    );
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
    expect(
      await requestsTo("DELETE", "/api/v1/bank-accounts/a1/"),
    ).toHaveLength(1);

    store.reset();
    expect(store.all).toEqual([]);
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("write order", () => {
  // GIVEN: a list refresh sent while an update of an account is in
  //        flight
  // WHEN:  the update lands first and the refresh answers afterwards
  //        with the account as it was
  // THEN:  the account keeps the update; the rest of the list is
  //        refreshed
  //
  it("keeps an update over an older list answer", async () => {
    withAuth();
    const account = makeBankAccount({ auto_funding_enabled: false });
    const other = makeBankAccount({ name: "Savings" });
    let answerList!: () => void;
    let answerPatch!: () => void;
    server.use(
      http.get(
        "/api/v1/bank-accounts/",
        () =>
          new Promise<Response>((resolve) => {
            answerList = () =>
              resolve(
                HttpResponse.json(
                  makePage([account, { ...other, name: "Rainy day" }]),
                ),
              );
          }),
      ),
      http.patch(
        `/api/v1/bank-accounts/${account.id}/`,
        () =>
          new Promise<Response>((resolve) => {
            answerPatch = () =>
              resolve(
                HttpResponse.json({ ...account, auto_funding_enabled: true }),
              );
          }),
      ),
    );
    const store = useBankAccountsStore();

    const update = store.update(account.id, { autoFundingEnabled: true });
    await vi.waitFor(() => expect(answerPatch).toBeDefined());
    const refresh = store.refresh();
    await vi.waitFor(() => expect(answerList).toBeDefined());
    answerPatch();
    await update;
    answerList();
    await refresh;

    expect
      .soft(store.byId(account.id)?.autoFundingEnabled, "update kept")
      .toBe(true);
    expect
      .soft(store.byId(other.id)?.name, "others refreshed")
      .toBe("Rainy day");
  });

  // GIVEN: a list refresh sent before a bank account is deleted
  // WHEN:  the delete lands first and the refresh answers afterwards
  //        with the bank account still listed
  // THEN:  the deleted bank account stays gone
  //
  it("keeps a deleted bank account gone", async () => {
    withAuth();
    const [kept, deleted] = [makeBankAccount(), makeBankAccount()];
    const store = useBankAccountsStore();
    store.setAll([kept, deleted].map(bankAccountFromDto));
    let answerList!: () => void;
    server.use(
      http.get(
        "/api/v1/bank-accounts/",
        () =>
          new Promise<Response>((resolve) => {
            answerList = () =>
              resolve(HttpResponse.json(makePage([kept, deleted])));
          }),
      ),
      http.delete(
        `/api/v1/bank-accounts/${deleted.id}/`,
        () => new HttpResponse(null, { status: 204 }),
      ),
    );

    const refresh = store.refresh();
    await vi.waitFor(() => expect(answerList).toBeDefined());
    await store.remove(deleted.id);
    answerList();
    await refresh;

    expect(store.all.map((a) => a.id)).toEqual([kept.id]);
  });

  // GIVEN: no list request in flight
  // WHEN:  two list refreshes are asked for at once
  // THEN:  one request is sent
  //
  it("shares one request between concurrent refreshes", async () => {
    withAuth();
    server.use(
      http.get("/api/v1/bank-accounts/", () =>
        HttpResponse.json(makePage([makeBankAccount()])),
      ),
    );
    const store = useBankAccountsStore();

    await Promise.all([store.refresh(), store.refresh()]);

    expect(await requestsTo("GET", "/api/v1/bank-accounts/")).toHaveLength(1);
  });
});
