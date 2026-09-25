//
// Account-context store tests: choosing the active bank account on
// init, persisting a switch, the shared `/users/me/` load, and the
// empty / error cases.
//

// 3rd party imports
//
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

// app imports
//
import type { BankAccountDto as BankAccount } from "@/api/dto";
import { bankAccountFromDto } from "@/models/bankAccount";
import { useAccountContextStore } from "@/stores/accountContext";
import { useSessionStore } from "@/stores/session";
import { withAuth } from "../helpers";
import { makeBankAccount, makePage, makeUser } from "../mocks/factories";
import { requestsTo, server } from "../mocks/server";

////////////////////////////////////////////////////////////////////////
//
const STORAGE_KEY = "mibudge.activeBankAccountId";

// Serve `accounts` from the bank-account list and `defaultId` as the
// user's `default_bank_account`.
//
function serveAccounts(accounts: BankAccount[], defaultId: string | null = null) {
  server.use(
    http.get("/api/v1/bank-accounts/", () => HttpResponse.json(makePage(accounts))),
    http.get("/api/v1/users/me/", () =>
      HttpResponse.json(makeUser({ default_bank_account: defaultId })),
    ),
  );
}

////////////////////////////////////////////////////////////////////////
//
describe("init", () => {
  // GIVEN: a tab whose sessionStorage names one of the user's accounts
  // WHEN:  the account context initialises
  // THEN:  that account is active, ahead of the server-side default
  //
  it("prefers the account stored in sessionStorage", async () => {
    withAuth();
    const [a, b, c] = [makeBankAccount(), makeBankAccount(), makeBankAccount()];
    serveAccounts([a, b, c], a.id);
    window.sessionStorage.setItem(STORAGE_KEY, b.id);
    const ctx = useAccountContextStore();

    await ctx.init();

    expect(ctx.accounts).toEqual([a, b, c].map(bankAccountFromDto));
    expect(ctx.activeBankAccountId).toBe(b.id);
    expect(ctx.activeBankAccount).toEqual(bankAccountFromDto(b));
    expect(ctx.unallocatedBudgetId).toBe(b.unallocated_budget);
  });

  // GIVEN: a stored account id that is no longer in the user's list
  // WHEN:  the account context initialises
  // THEN:  the user's default account is chosen and persisted instead
  //
  it("falls back to the default account when the stored id is stale", async () => {
    withAuth().user = null;
    const [a, b] = [makeBankAccount(), makeBankAccount()];
    serveAccounts([a, b], b.id);
    window.sessionStorage.setItem(STORAGE_KEY, "no-longer-mine");
    const ctx = useAccountContextStore();

    await ctx.init();

    expect(ctx.activeBankAccountId).toBe(b.id);
    expect(window.sessionStorage.getItem(STORAGE_KEY)).toBe(b.id);
  });

  // GIVEN: no stored id and no valid default account
  // WHEN:  the account context initialises
  // THEN:  the first account in the list is chosen
  //
  it("falls back to the first account", async () => {
    withAuth().user = null;
    const [a, b] = [makeBankAccount(), makeBankAccount()];
    serveAccounts([a, b], "someone-elses-account");
    const ctx = useAccountContextStore();

    await ctx.init();

    expect(ctx.activeBankAccountId).toBe(a.id);
  });

  // GIVEN: a `/users/me/` request that fails
  // WHEN:  the account context initialises
  // THEN:  the account list still loads and the first account is chosen
  //
  it("tolerates a failed user lookup", async () => {
    withAuth().user = null;
    const a = makeBankAccount();
    serveAccounts([a]);
    server.use(http.get("/api/v1/users/me/", () => new HttpResponse(null, { status: 500 })));
    const ctx = useAccountContextStore();

    await ctx.init();

    expect(ctx.activeBankAccountId).toBe(a.id);
    expect(ctx.error).toBeNull();
  });

  // GIVEN: a user with no bank accounts
  // WHEN:  the account context initialises
  // THEN:  no account is active and nothing is stored
  //
  it("handles an empty account list", async () => {
    withAuth();
    serveAccounts([]);
    window.sessionStorage.setItem(STORAGE_KEY, "stale");
    const ctx = useAccountContextStore();

    await ctx.init();

    expect(ctx.accounts).toEqual([]);
    expect(ctx.activeBankAccountId).toBeNull();
    expect(ctx.activeBankAccount).toBeNull();
    expect(ctx.unallocatedBudgetId).toBeNull();
    expect(window.sessionStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  // GIVEN: a bank-account list request that fails
  // WHEN:  the account context initialises
  // THEN:  the error is recorded and loading ends
  //
  it("records an error when the account list fails", async () => {
    withAuth();
    server.use(http.get("/api/v1/bank-accounts/", () => new HttpResponse(null, { status: 500 })));
    const ctx = useAccountContextStore();

    await ctx.init();

    expect(ctx.error).toBe("Failed to load bank accounts. (HTTP 500)");
    expect(ctx.loading).toBe(false);
  });

  // GIVEN: an already-initialised account context
  // WHEN:  `init()` runs again without `force`
  // THEN:  no new request is made; with `force` the list is reloaded
  //
  it("loads once per session unless forced", async () => {
    withAuth();
    serveAccounts([makeBankAccount()]);
    const ctx = useAccountContextStore();

    await ctx.init();
    await ctx.init();
    expect(await requestsTo("GET", "/api/v1/bank-accounts/")).toHaveLength(1);

    await ctx.init(true);
    expect(await requestsTo("GET", "/api/v1/bank-accounts/")).toHaveLength(2);
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("cold boot", () => {
  // GIVEN: a session with no user loaded yet
  // WHEN:  the user and the account context load at the same time, as
  //        they do on a cold boot
  // THEN:  `/users/me/` is requested once
  //  AND:  the user's default account is chosen
  //
  it("requests /users/me/ once", async () => {
    const session = withAuth();
    session.user = null;
    const [a, b] = [makeBankAccount(), makeBankAccount()];
    serveAccounts([a, b], b.id);
    const ctx = useAccountContextStore();

    await Promise.all([session.loadUser(), ctx.init()]);

    expect(await requestsTo("GET", "/api/v1/users/me/")).toHaveLength(1);
    expect(ctx.activeBankAccountId).toBe(b.id);
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("switching accounts", () => {
  // GIVEN: an initialised account context
  // WHEN:  the user switches to another account
  // THEN:  it becomes active and is persisted to sessionStorage
  //
  it("persists the switch", async () => {
    withAuth();
    const [a, b] = [makeBankAccount(), makeBankAccount()];
    serveAccounts([a, b]);
    const ctx = useAccountContextStore();
    await ctx.init();

    ctx.setActive(b.id);

    expect(ctx.activeBankAccountId).toBe(b.id);
    expect(window.sessionStorage.getItem(STORAGE_KEY)).toBe(b.id);
  });

  // GIVEN: an active account
  // WHEN:  the user signs out
  // THEN:  the accounts, the active id and the stored id are removed
  //
  it("sign-out removes the active account and the stored id", async () => {
    withAuth();
    serveAccounts([makeBankAccount()]);
    const ctx = useAccountContextStore();
    await ctx.init();

    useSessionStore().logout();

    expect(ctx.accounts).toEqual([]);
    expect(ctx.activeBankAccountId).toBeNull();
    expect(window.sessionStorage.getItem(STORAGE_KEY)).toBeNull();
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("refresh", () => {
  // GIVEN: an active account
  // WHEN:  the account list is refreshed
  // THEN:  the accounts are replaced and the active id is unchanged
  //
  it("reloads accounts and keeps the active id", async () => {
    withAuth();
    const a = makeBankAccount({ name: "Old name" });
    serveAccounts([a]);
    const ctx = useAccountContextStore();
    await ctx.init();
    serveAccounts([{ ...a, name: "New name" }]);

    await ctx.refresh();

    expect(ctx.activeBankAccount?.name).toBe("New name");
    expect(ctx.activeBankAccountId).toBe(a.id);
  });

  // GIVEN: an active account that has since been deleted
  // WHEN:  the account list is refreshed
  // THEN:  the first remaining account becomes active
  //
  it("moves off an account that no longer exists", async () => {
    withAuth();
    const [a, b] = [makeBankAccount(), makeBankAccount()];
    serveAccounts([a, b]);
    const ctx = useAccountContextStore();
    await ctx.init();
    ctx.setActive(b.id);
    serveAccounts([a]);

    await ctx.refresh();

    expect(ctx.activeBankAccountId).toBe(a.id);
  });
});
