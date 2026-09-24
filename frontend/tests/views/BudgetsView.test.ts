//
// BudgetsView tests: the view, its stores, the API modules and the
// transport rendering data from the mock REST API.
//

// 3rd party imports
//
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

// app imports
//
import BudgetCard from "@/components/budgets/BudgetCard.vue";
import { useAccountContextStore } from "@/stores/accountContext";
import type { BankAccount } from "@/types/api";
import BudgetsView from "@/views/BudgetsView.vue";
import { mountWithApp, withAuth } from "../helpers";
import { makeBankAccount, makeBudget, makePage } from "../mocks/factories";
import { requestsTo, server } from "../mocks/server";

////////////////////////////////////////////////////////////////////////
//
describe("BudgetsView", () => {
  let account: BankAccount;

  beforeEach(() => {
    withAuth();
    account = makeBankAccount({ name: "Household" });
    const ctx = useAccountContextStore();
    ctx.accounts = [account];
    ctx.setActive(account.id);
  });

  // GIVEN: an active bank account with recurring, goal and fill-up budgets
  // WHEN:  the budgets view is opened
  // THEN:  it requests the account's non-archived budgets by name
  //  AND:  it lists each standalone budget from the response by name,
  //        grouped under Recurring and Goals, without the unallocated
  //        budget or fill-up goals
  //
  it("renders the budgets returned by the API", async () => {
    const budgets = [
      makeBudget({ name: "Rent", budget_type: "R", bank_account: account.id }),
      makeBudget({ name: "Vacation", budget_type: "G", bank_account: account.id }),
      makeBudget({ name: "Rent fill-up", budget_type: "A", bank_account: account.id }),
      makeBudget({
        id: account.unallocated_budget,
        name: "Unallocated",
        bank_account: account.id,
      }),
    ];
    server.use(http.get("/api/v1/budgets/", () => HttpResponse.json(makePage(budgets))));

    const { wrapper } = await mountWithApp(BudgetsView, { route: "/budgets/" });

    const cards = wrapper.findAllComponents(BudgetCard);
    expect(cards.map((c) => c.props("budget").name)).toEqual(["Rent", "Vacation"]);
    expect(cards.map((c) => c.text())).toEqual([
      expect.stringContaining("Rent"),
      expect.stringContaining("Vacation"),
    ]);
    const headings = wrapper.findAll("h2").map((h) => h.text());
    expect(headings).toEqual(["Recurring", "Goals"]);
    const [listReq] = await requestsTo("GET", "/api/v1/budgets/");
    expect(listReq.path).toBe(
      `/api/v1/budgets/?bank_account=${account.id}&archived=false&ordering=name`,
    );
  });

  // GIVEN: an active bank account with no budgets
  // WHEN:  the budgets view is opened
  // THEN:  the empty state is shown
  //
  it("shows the empty state when there are no budgets", async () => {
    server.use(http.get("/api/v1/budgets/", () => HttpResponse.json(makePage([]))));

    const { wrapper } = await mountWithApp(BudgetsView, { route: "/budgets/" });

    expect(wrapper.text()).toContain("No budgets yet");
  });

  // GIVEN: an active bank account
  // WHEN:  the budget list endpoint answers 500
  // THEN:  the view shows the error message instead of the list
  //
  it("shows the error state when the endpoint fails", async () => {
    server.use(http.get("/api/v1/budgets/", () => new HttpResponse(null, { status: 500 })));

    const { wrapper } = await mountWithApp(BudgetsView, { route: "/budgets/" });

    expect(wrapper.text()).toContain("HTTP 500");
    expect(wrapper.text()).not.toContain("No budgets yet");
  });
});
