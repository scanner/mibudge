//
// Account tab, profile, budget-create and overview tests against the
// mock REST API.
//

// 3rd party imports
//
import { flushPromises } from "@vue/test-utils";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

// app imports
//
import App from "@/App.vue";
import { budgetFromDto } from "@/models/budget";
import { useAccountContextStore } from "@/stores/accountContext";
import { useBudgetsStore } from "@/stores/budgets";
import { useSessionStore } from "@/stores/session";
import { useTransactionNavStore } from "@/stores/transactionNav";
import { mountWithApp, withAccounts, withAuth } from "../helpers";
import {
  makeBankAccount,
  makeBudget,
  makeFundingSummary,
  makePage,
  makeTransaction,
  makeUser,
} from "../mocks/factories";
import { requestsTo, server } from "../mocks/server";

////////////////////////////////////////////////////////////////////////
//
type Wrapper = Awaited<ReturnType<typeof mountWithApp>>["wrapper"];

function button(wrapper: Wrapper, text: string) {
  return wrapper.findAll("button").find((b) => b.text().trim().includes(text))!;
}

async function open(path: string) {
  const mounted = await mountWithApp(App, { route: path });
  await vi.waitFor(() => expect(mounted.wrapper.find("main").exists()).toBe(true));
  await flushPromises();
  return mounted;
}

let account: ReturnType<typeof makeBankAccount>;

beforeEach(() => {
  withAuth(undefined, makeUser({ name: "Ada Lovelace", username: "ada" }));
  account = makeBankAccount({ name: "Household" });
  withAccounts([account]);
  server.use(http.get("/api/v1/bank-accounts/", () => HttpResponse.json(makePage([account]))));
});

////////////////////////////////////////////////////////////////////////
//
describe("AccountView", () => {
  // GIVEN: a signed-in user with cached budgets and a remembered list
  // WHEN:  they sign out
  // THEN:  every store is emptied and the login page opens
  //
  it("sign-out resets every store", async () => {
    const { wrapper, router } = await open("/account/");
    expect(wrapper.text()).toContain("AL");
    useBudgetsStore().upsert(budgetFromDto(makeBudget()));
    useTransactionNavStore().setIds(["a"]);

    await button(wrapper, "Sign out").trigger("click");
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe("login"));

    expect(useSessionStore().isAuthenticated).toBe(false);
    expect(useBudgetsStore().all).toEqual([]);
    expect(useTransactionNavStore().orderedIds).toEqual([]);
    expect(useAccountContextStore().accounts).toEqual([]);
  });

  // GIVEN: an account with a funding event
  // WHEN:  the Account tab opens and the user picks a default account
  // THEN:  the next funding total is shown, and the default is saved
  //
  it("shows funding and saves the default account", async () => {
    server.use(
      http.get(`/api/v1/bank-accounts/${account.id}/funding-summary/`, () =>
        HttpResponse.json(makeFundingSummary({ total_amount: "40.00" })),
      ),
    );
    const { wrapper } = await open("/account/");
    await vi.waitFor(() => expect(wrapper.text()).toContain("next event"));

    await wrapper.get("select").setValue(account.id);
    await flushPromises();

    const [patch] = await requestsTo("PATCH", "/api/v1/users/me/");
    expect(patch.body).toEqual({ default_bank_account: account.id });
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("UserProfileView", () => {
  // GIVEN: the profile form
  // WHEN:  the user changes their timezone and saves
  // THEN:  the profile is saved, the session's timezone follows, and the
  //        Account tab opens
  //
  it("saves the profile", async () => {
    const { wrapper, router } = await open("/account/profile/");
    await wrapper.get("#profile-timezone").setValue("Asia/Tokyo");
    await wrapper.findAll("form")[0].trigger("submit");
    await flushPromises();

    expect(useSessionStore().timezone).toBe("Asia/Tokyo");
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe("account"));
  });

  // GIVEN: the email-change form
  // WHEN:  the server answers 409
  // THEN:  the in-use message is shown
  //
  it("explains a conflicting email change", async () => {
    server.use(
      http.post("/api/v1/users/me/change-email/", () => HttpResponse.json({}, { status: 409 })),
    );
    const { wrapper } = await open("/account/profile/");
    await wrapper.get('input[type="email"]').setValue("new@example.com");
    await wrapper.findAll("form")[1].trigger("submit");
    await flushPromises();
    expect(wrapper.text()).toContain("already in use");
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("BudgetCreateView", () => {
  // GIVEN: the new-budget form
  // WHEN:  the user creates a capped budget with typed amounts
  // THEN:  the amounts are sent as two-decimal strings, not numbers
  //  AND:  the new budget's page opens
  //
  it("creates a budget with decimal-string amounts", async () => {
    const { wrapper, router } = await open("/budgets/create/");

    await button(wrapper, "Capped").trigger("click");
    await wrapper.get("#budget-name").setValue("Groceries");
    await wrapper.get("#target-balance").setValue("400");
    await wrapper.get("#funding-amount").setValue("50.5");
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    const [post] = await requestsTo("POST", "/api/v1/budgets/");
    expect(post.body).toMatchObject({
      name: "Groceries",
      budget_type: "C",
      bank_account: account.id,
      target_balance: "400.00",
      funding_amount: "50.50",
      funding_type: "F",
    });
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe("budget-detail"));
  });

  // GIVEN: a recurring budget with a next refresh date
  // WHEN:  it is created
  // THEN:  the refresh cycle is sent interval-only with the date as DTSTART
  //
  it("anchors a recurring budget's refresh cycle", async () => {
    const { wrapper } = await open("/budgets/create/");
    await wrapper.get("#budget-name").setValue("Rent");
    await wrapper.get("#target-balance").setValue("1500");
    await wrapper.get("#next-refresh-date").setValue("2026-10-01");
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    const [post] = await requestsTo("POST", "/api/v1/budgets/");
    expect(post.body).toMatchObject({
      budget_type: "R",
      recurrence_schedule: "DTSTART:20261001T000000Z\nRRULE:FREQ=MONTHLY",
    });
  });

  // GIVEN: the server rejects the budget
  // WHEN:  it is submitted
  // THEN:  the server's message is shown
  //
  it("shows the server's error", async () => {
    server.use(
      http.post("/api/v1/budgets/", () =>
        HttpResponse.json({ name: ["A budget with this name exists."] }, { status: 400 }),
      ),
    );
    const { wrapper } = await open("/budgets/create/");
    await wrapper.get("#budget-name").setValue("Rent");
    await wrapper.get("#target-balance").setValue("1500");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(wrapper.text()).toContain("A budget with this name exists.");
  });

  // GIVEN: the new-budget form with a name but no target amount
  // WHEN:  it is submitted
  // THEN:  nothing is sent and the form asks for a target, rather than
  //        creating a budget with a $0.00 target
  //
  it("requires a target amount", async () => {
    const { wrapper } = await open("/budgets/create/");
    await wrapper.get("#budget-name").setValue("Rent");
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(await requestsTo("POST", "/api/v1/budgets/")).toHaveLength(0);
    expect(wrapper.text()).toContain("Enter a target amount.");
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("OverviewView", () => {
  // GIVEN: budgets and recent transactions for the active account
  // WHEN:  the overview opens
  // THEN:  standalone budgets and recent transactions are listed, and
  //        a transaction opens its detail page
  //
  it("shows budgets and recent transactions", async () => {
    const rent = makeBudget({ name: "Rent", budget_type: "R", bank_account: account.id });
    const fill = makeBudget({ name: "Rent fill", budget_type: "A", bank_account: account.id });
    const tx = makeTransaction({ bank_account: account.id, party: "Corner Market" });
    server.use(
      http.get("/api/v1/budgets/", () =>
        HttpResponse.json(makePage([{ ...rent, fillup_goal: fill.id }, fill])),
      ),
      http.get("/api/v1/transactions/", () => HttpResponse.json(makePage([tx]))),
      http.get(`/api/v1/bank-accounts/${account.id}/funding-summary/`, () =>
        HttpResponse.json(
          makeFundingSummary({ total_amount: "40.00", schedules: [{ next_date: "2026-10-01" }] }),
        ),
      ),
    );
    const { wrapper, router } = await open("/");

    await vi.waitFor(() => expect(wrapper.text()).toContain("Corner Market"));
    expect(wrapper.text()).toContain("Rent");
    expect(wrapper.text()).not.toContain("Rent fill");
    expect(wrapper.text()).toContain("Funded automatically");

    await wrapper
      .findAll("article")
      .find((a) => a.text().includes("Corner Market"))!
      .trigger("click");
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe("transaction-detail"));
  });

  // GIVEN: the overview, which lists the five most recent transactions
  // WHEN:  it loads
  // THEN:  it asks the server for a page of five, not a full page
  //
  it("requests only the recent transactions it shows", async () => {
    server.use(
      http.get(`/api/v1/bank-accounts/${account.id}/funding-summary/`, () =>
        HttpResponse.json(makeFundingSummary()),
      ),
    );
    await open("/");

    const [list] = await requestsTo("GET", "/api/v1/transactions/");
    expect(new URL(list.url).searchParams.get("page_size")).toBe("5");
  });
});
