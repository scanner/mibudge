//
// BudgetDetailView tests: the app rendered at `/budgets/<id>/` through
// the real router, stores, API modules and transport, with only the
// network mocked.
//

// 3rd party imports
//
import { flushPromises } from "@vue/test-utils";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

// app imports
//
import App from "@/App.vue";
import { useBudgetsStore } from "@/stores/budgets";
import { mountWithApp, withAccounts, withAuth } from "../helpers";
import {
  makeAllocation,
  makeBankAccount,
  makeBudget,
  makePage,
  makeTransaction,
} from "../mocks/factories";
import { requestsTo, server } from "../mocks/server";

////////////////////////////////////////////////////////////////////////
//
describe("BudgetDetailView", () => {
  let account: ReturnType<typeof makeBankAccount>;

  beforeEach(() => {
    withAuth();
    account = makeBankAccount();
    withAccounts([account]);
  });

  function serveBudgets(budgets: ReturnType<typeof makeBudget>[]) {
    const byId = new Map(budgets.map((b) => [b.id, b]));
    server.use(
      http.get("/api/v1/budgets/:id/", ({ params }) =>
        HttpResponse.json(byId.get(String(params.id))),
      ),
    );
  }

  // GIVEN: the detail view of budget A
  // WHEN:  the route is reused for budget B (same view, new id)
  // THEN:  budget B is loaded and shown
  //
  it("reloads when the route's id changes", async () => {
    const a = makeBudget({ name: "Groceries", bank_account: account.id });
    const b = makeBudget({ name: "Vacation", bank_account: account.id });
    serveBudgets([a, b]);
    const { wrapper, router } = await mountWithApp(App, {
      route: `/budgets/${a.id}/`,
    });
    await vi.waitFor(() => expect(wrapper.find("h1").text()).toBe("Groceries"));

    await router.push(`/budgets/${b.id}/`);
    await flushPromises();

    await vi.waitFor(() => expect(wrapper.find("h1").text()).toBe("Vacation"));
    expect(await requestsTo("GET", `/api/v1/budgets/${b.id}/`)).toHaveLength(1);
  });

  // GIVEN: a budget with one allocated transaction
  // WHEN:  the view opens
  // THEN:  the budget's transactions are asked for in one list request
  //  AND:  the transaction is listed under its date
  //
  it("lists the budget's transactions", async () => {
    const budget = makeBudget({ name: "Groceries", bank_account: account.id });
    const tx = makeTransaction({
      bank_account: account.id,
      party: "Corner Market",
      allocations: [makeAllocation({ budget: budget.id, amount: "-12.34" })],
    });
    serveBudgets([budget]);
    server.use(
      http.get("/api/v1/transactions/", ({ request }) =>
        HttpResponse.json(
          makePage(
            new URL(request.url).searchParams.get("budget") === budget.id
              ? [tx]
              : [],
          ),
        ),
      ),
    );

    const { wrapper } = await mountWithApp(App, {
      route: `/budgets/${budget.id}/`,
    });

    await vi.waitFor(() => expect(wrapper.text()).toContain("Corner Market"));
    expect(await requestsTo("GET", "/api/v1/transactions/")).toHaveLength(1);
  });

  // GIVEN: a $100 transaction split $40 to this budget and $60 to Rent
  // WHEN:  the user removes it from this budget
  // THEN:  the split re-declares only Rent's share (the rest goes to
  //        Unallocated), the row leaves the list, and the account's
  //        budgets are refetched
  //
  it("removes a split transaction from the budget", async () => {
    const budget = makeBudget({ name: "Groceries", bank_account: account.id });
    const rent = makeBudget({ name: "Rent", bank_account: account.id });
    const tx = makeTransaction({
      bank_account: account.id,
      party: "Corner Market",
      amount: "-100.00",
      allocations: [
        makeAllocation({ budget: budget.id, amount: "-40.00" }),
        makeAllocation({ budget: rent.id, amount: "-60.00" }),
      ],
    });
    serveBudgets([budget, rent]);
    server.use(
      http.get("/api/v1/transactions/", () =>
        HttpResponse.json(makePage([tx])),
      ),
      http.get(`/api/v1/transactions/${tx.id}/`, () => HttpResponse.json(tx)),
      http.post(`/api/v1/transactions/${tx.id}/splits/`, () =>
        HttpResponse.json([]),
      ),
    );
    const { wrapper } = await mountWithApp(App, {
      route: `/budgets/${budget.id}/`,
    });
    await vi.waitFor(() => expect(wrapper.text()).toContain("Corner Market"));
    const budgetLoadsBefore = (await requestsTo("GET", "/api/v1/budgets/"))
      .length;

    await wrapper
      .get('button[aria-label="Remove from budget"]')
      .trigger("click");
    await flushPromises();

    const [post] = await requestsTo(
      "POST",
      `/api/v1/transactions/${tx.id}/splits/`,
    );
    expect(post.body).toEqual({ splits: { [rent.id]: "60.00" } });
    await vi.waitFor(() =>
      expect(wrapper.text()).not.toContain("Corner Market"),
    );
    expect(
      (await requestsTo("GET", "/api/v1/budgets/")).length,
    ).toBeGreaterThan(budgetLoadsBefore);
  });

  // GIVEN: a budget whose loaded page holds only a recent transaction
  // WHEN:  the user searches for an older one
  // THEN:  the server is searched within this budget, and its older
  //        match is listed
  //
  it("searches the budget's older transactions", async () => {
    const budget = makeBudget({ name: "Groceries", bank_account: account.id });
    const recent = makeTransaction({ party: "Hardware Store" });
    const older = makeTransaction({ party: "Copper Kettle Coffee" });
    serveBudgets([budget]);
    server.use(
      http.get("/api/v1/transactions/", ({ request }) =>
        HttpResponse.json(
          makePage(
            new URL(request.url).searchParams.get("search")
              ? [older]
              : [recent],
          ),
        ),
      ),
    );
    const { wrapper } = await mountWithApp(App, {
      route: `/budgets/${budget.id}/`,
    });
    await vi.waitFor(() => expect(wrapper.text()).toContain("Hardware Store"));

    await wrapper
      .get('button[aria-label="Search transactions"]')
      .trigger("click");
    await wrapper
      .get('input[placeholder="Search transactions…"]')
      .setValue("kettle");

    await vi.waitFor(() =>
      expect(wrapper.text()).toContain("Copper Kettle Coffee"),
    );
    const search = (await requestsTo("GET", "/api/v1/transactions/"))
      .map((r) => new URL(r.url).searchParams)
      .find((q) => q.has("search"))!;
    expect(search.get("search")).toBe("kettle");
    expect(search.get("budget")).toBe(budget.id);
  });

  // GIVEN: a budget
  // WHEN:  the user pauses it
  // THEN:  the PATCH is sent and the button offers to resume
  //
  it("pauses the budget", async () => {
    const budget = makeBudget({
      name: "Groceries",
      bank_account: account.id,
      paused: false,
    });
    serveBudgets([budget]);
    const { wrapper } = await mountWithApp(App, {
      route: `/budgets/${budget.id}/`,
    });
    await vi.waitFor(() => expect(wrapper.find("h1").exists()).toBe(true));

    await wrapper
      .findAll("button")
      .find((b) => b.text().includes("Pause budget"))!
      .trigger("click");
    await flushPromises();

    const [patch] = await requestsTo("PATCH", `/api/v1/budgets/${budget.id}/`);
    expect(patch.body).toEqual({ paused: true });
    expect(wrapper.text()).toContain("Resume budget");
  });

  // GIVEN: a budget and the Unallocated budget of its account
  // WHEN:  the user moves 25.00 into the budget from Unallocated
  // THEN:  the transfer is posted with a two-decimal string amount
  //  AND:  both budgets are refetched into the cache
  //
  it("moves money into the budget", async () => {
    const budget = makeBudget({ name: "Groceries", bank_account: account.id });
    const unalloc = makeBudget({
      id: account.unallocated_budget!,
      name: "Unallocated",
      bank_account: account.id,
    });
    serveBudgets([budget, unalloc]);
    server.use(
      http.get("/api/v1/budgets/", () =>
        HttpResponse.json(makePage([budget, unalloc])),
      ),
    );
    const { wrapper } = await mountWithApp(App, {
      route: `/budgets/${budget.id}/`,
    });
    await vi.waitFor(() => expect(wrapper.find("h1").exists()).toBe(true));

    await wrapper
      .findAll("button")
      .find((b) => b.text().includes("Move money"))!
      .trigger("click");
    await flushPromises();
    const amount = document.body.querySelector<HTMLInputElement>(
      'input[type="number"]',
    )!;
    amount.value = "25";
    amount.dispatchEvent(new Event("input"));
    await flushPromises();
    Array.from(document.body.querySelectorAll("button"))
      .find((b) => b.textContent?.trim() === "Transfer")!
      .click();
    await flushPromises();

    const [post] = await requestsTo("POST", "/api/v1/internal-transactions/");
    expect(post.body).toEqual({
      bank_account: account.id,
      src_budget: unalloc.id,
      dst_budget: budget.id,
      amount: "25.00",
    });
    expect(useBudgetsStore().byId(unalloc.id)).not.toBeNull();
  });
});
