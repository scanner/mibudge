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
    server.use(
      http.get("/api/v1/allocations/", () => HttpResponse.json(makePage([]))),
    );
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
  // THEN:  the transaction is listed under its date
  //
  it("lists the budget's transactions", async () => {
    const budget = makeBudget({ name: "Groceries", bank_account: account.id });
    const tx = makeTransaction({
      bank_account: account.id,
      party: "Corner Market",
      amount: "-12.34",
    });
    serveBudgets([budget]);
    server.use(
      http.get("/api/v1/allocations/", () =>
        HttpResponse.json(
          makePage([
            makeAllocation({
              transaction: tx.id,
              budget: budget.id,
              amount: "-12.34",
            }),
          ]),
        ),
      ),
      http.get(`/api/v1/transactions/${tx.id}/`, () => HttpResponse.json(tx)),
    );

    const { wrapper } = await mountWithApp(App, {
      route: `/budgets/${budget.id}/`,
    });

    await vi.waitFor(() => expect(wrapper.text()).toContain("Corner Market"));
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
