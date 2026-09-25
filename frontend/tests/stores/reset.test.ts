//
// Store reset tests: every store defines `reset()`, and signing out
// empties every store that holds data.
//

// 3rd party imports
//
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

// app imports
//
import { allocationFromDto } from "@/models/allocation";
import { budgetFromDto } from "@/models/budget";
import { useAccountContextStore } from "@/stores/accountContext";
import { useAllocationsStore } from "@/stores/allocations";
import { useBankAccountsStore } from "@/stores/bankAccounts";
import { useBudgetsStore } from "@/stores/budgets";
import { useSessionStore } from "@/stores/session";
import { useTransactionNavStore } from "@/stores/transactionNav";
import { withAccounts, withAuth } from "../helpers";
import {
  makeAllocation,
  makeBankAccount,
  makeBudget,
  makePage,
} from "../mocks/factories";
import { server } from "../mocks/server";

////////////////////////////////////////////////////////////////////////
//
// Every `use*Store` exported from `src/stores/`, loaded by file so a new
// store is covered without editing this test.
//
const storeModules = import.meta.glob<Record<string, unknown>>(
  "../../src/stores/*.ts",
  {
    eager: true,
  },
);
const storeFactories = Object.entries(storeModules).flatMap(([file, mod]) =>
  Object.entries(mod)
    .filter(
      ([name, value]) =>
        /^use\w+Store$/.test(name) && typeof value === "function",
    )
    .map(
      ([name, value]) =>
        [`${file}: ${name}`, value as () => { reset?: unknown }] as const,
    ),
);

////////////////////////////////////////////////////////////////////////
//
describe("store reset", () => {
  // GIVEN: every store in `src/stores/`
  // WHEN:  it is created
  // THEN:  it has a `reset()` action for sign-out to call
  //
  it.each(storeFactories)("%s defines reset()", (_name, useStore) => {
    expect(typeof useStore().reset).toBe("function");
  });

  // GIVEN: a signed-in session with accounts, budgets, allocations and
  //        a remembered list position
  // WHEN:  the user signs out
  // THEN:  every store is empty and the tab's stored account is gone
  //
  it("sign-out empties every store", () => {
    withAuth();
    const account = makeBankAccount();
    withAccounts([account]);
    const budgets = useBudgetsStore();
    budgets.upsert(budgetFromDto(makeBudget()));
    const allocations = useAllocationsStore();
    allocations.invalidate();
    const nav = useTransactionNavStore();
    nav.setIds(["a", "b"]);
    nav.savedSearch = "coffee";
    // Seed an allocation index by hand (normally fetched).
    allocations.setForTransaction(account.id, "t", [
      allocationFromDto(makeAllocation()),
    ]);

    useSessionStore().logout();

    expect(useSessionStore().isAuthenticated).toBe(false);
    expect(useBankAccountsStore().all).toEqual([]);
    expect(useAccountContextStore().activeBankAccountId).toBeNull();
    expect(budgets.all).toEqual([]);
    expect(allocations.indexFor(account.id)).toBeNull();
    expect(nav.orderedIds).toEqual([]);
    expect(nav.savedSearch).toBe("");
    expect(
      window.sessionStorage.getItem("mibudge.activeBankAccountId"),
    ).toBeNull();
  });

  // GIVEN: a list load in flight for the signed-in user
  // WHEN:  the user signs out, then the load's response arrives
  // THEN:  the store stays empty; the previous user's data is not
  //        written back
  //
  it.each([
    [
      "budgets",
      "/api/v1/budgets/",
      () => makePage([makeBudget()]),
      () => useBudgetsStore().fetchList(),
      () => useBudgetsStore().all,
    ],
    [
      "bank accounts",
      "/api/v1/bank-accounts/",
      () => makePage([makeBankAccount()]),
      () => useBankAccountsStore().loadAll(true),
      () => useBankAccountsStore().all,
    ],
  ])(
    "sign-out drops a late %s response",
    async (_name, path, body, load, cached) => {
      withAuth();
      let release!: () => void;
      const gate = new Promise<void>((resolve) => (release = resolve));
      server.use(
        http.get(path, async () => {
          await gate;
          return HttpResponse.json(body());
        }),
      );

      const pending = load().catch(() => undefined);
      await new Promise((resolve) => setTimeout(resolve, 10));
      useSessionStore().logout();
      release();
      await pending;

      expect(cached()).toEqual([]);
    },
  );
});
