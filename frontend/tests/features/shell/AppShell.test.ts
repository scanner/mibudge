//
// AppShell tests: the account-context header (TopBar) and the account
// switcher, wired to the stores by the shell.  One test spies on store
// actions with `createTestingPinia` to check what the shell asks the
// budgets store for; the others run the real stores against the mock
// REST API.
//

// 3rd party imports
//
import { createTestingPinia } from "@pinia/testing";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

// app imports
//
import AppShell from "@/features/shell/AppShell.vue";
import { bankAccountFromDto } from "@/models/bankAccount";
import { useAccountContextStore } from "@/stores/accountContext";
import { useBudgetsStore } from "@/stores/budgets";
import { mountWithApp, withAccounts, withAuth } from "../../helpers";
import { makeBankAccount, makeBudget } from "../../mocks/factories";
import { requestsTo, server } from "../../mocks/server";

////////////////////////////////////////////////////////////////////////
//
describe("AppShell", () => {
  // GIVEN: an active account whose unallocated budget is not cached
  // WHEN:  the top bar renders
  // THEN:  it shows the account name and a placeholder for the
  //        unallocated amount
  //  AND:  it asks the budgets store to fetch the unallocated budget
  //
  it("requests the unallocated budget for the active account", async () => {
    const account = makeBankAccount({ name: "Household" });
    // Actions are spied on and still run (`stubActions: false`): the
    // shell reads accounts through `bankAccounts.byId`, which a stub
    // would blank out.  The spied `fetchOne` is held pending so the
    // placeholder stays on screen.
    //
    const pinia = createTestingPinia({
      createSpy: vi.fn,
      stubActions: false,
      initialState: {
        session: { accessToken: "t" },
        bankAccounts: { accounts: [bankAccountFromDto(account)], loaded: true },
        accountContext: { activeBankAccountId: account.id },
      },
    });
    const budgets = useBudgetsStore(pinia);
    vi.mocked(budgets.fetchOne).mockImplementation(() => new Promise(() => undefined));

    const { wrapper } = await mountWithApp(AppShell, { route: "/budgets/", pinia });

    expect(wrapper.text()).toContain("Household, Available:");
    expect(wrapper.text()).toContain("—");
    expect(budgets.fetchOne).toHaveBeenCalledWith(account.unallocated_budget);
  });

  // GIVEN: an active account and its unallocated budget on the server
  // WHEN:  the top bar renders
  // THEN:  the unallocated balance from the API is shown
  //
  it("shows the unallocated balance fetched from the API", async () => {
    withAuth();
    const account = makeBankAccount();
    const unallocated = makeBudget({ id: account.unallocated_budget!, balance: "42.50" });
    server.use(
      http.get(`/api/v1/budgets/${unallocated.id}/`, () => HttpResponse.json(unallocated)),
    );
    withAccounts([account]);

    const { wrapper } = await mountWithApp(AppShell, { route: "/budgets/" });

    expect(wrapper.text()).toContain("42.50");
    expect(await requestsTo("GET", `/api/v1/budgets/${unallocated.id}/`)).toHaveLength(1);
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("account switcher", () => {
  // GIVEN: two accounts, the first active
  // WHEN:  the user opens the switcher and picks the second
  // THEN:  the second account becomes active and the sheet closes
  //
  it("switches the active account", async () => {
    withAuth();
    const [a, b] = [makeBankAccount({ name: "One" }), makeBankAccount({ name: "Two" })];
    withAccounts([a, b]);

    const { wrapper } = await mountWithApp(AppShell, { route: "/budgets/" });
    await wrapper.get('button[aria-label="Switch bank account"]').trigger("click");
    const dialog = document.body.querySelector('[role="dialog"]');
    expect(dialog?.textContent).toContain("Two");
    const choice = Array.from(dialog!.querySelectorAll("button")).find((el) =>
      el.textContent?.includes("Two"),
    );
    choice!.click();
    await wrapper.vm.$nextTick();

    expect(useAccountContextStore().activeBankAccountId).toBe(b.id);
    expect(document.body.querySelector('[role="dialog"]')).toBeNull();
  });

  // GIVEN: a budget's or a transaction's detail page, which belongs to
  //        the active account
  // WHEN:  the user switches to another account
  // THEN:  the page moves to that section's list for the new account,
  //        instead of showing the old account's record under the new
  //        account's name
  //
  it.each([
    ["/budgets/00000000-0000-4000-8000-000000000001/", "budgets"],
    ["/transactions/00000000-0000-4000-8000-000000000001/", "transactions"],
  ])("leaves %s for its list on an account switch", async (route, listName) => {
    withAuth();
    const [a, b] = [makeBankAccount({ name: "One" }), makeBankAccount({ name: "Two" })];
    withAccounts([a, b]);

    const { wrapper, router } = await mountWithApp(AppShell, { route });
    await wrapper.get('button[aria-label="Switch bank account"]').trigger("click");
    const dialog = document.body.querySelector('[role="dialog"]');
    const choice = Array.from(dialog!.querySelectorAll("button")).find((el) =>
      el.textContent?.includes("Two"),
    );
    choice!.click();

    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe(listName));
  });

  // GIVEN: the switcher open
  // WHEN:  the user picks "Manage accounts"
  // THEN:  the Account tab opens
  //
  it("navigates to the account tab", async () => {
    withAuth();
    withAccounts([makeBankAccount()]);

    const { wrapper, router } = await mountWithApp(AppShell, { route: "/budgets/" });
    await wrapper.get('button[aria-label="Switch bank account"]').trigger("click");
    const manage = Array.from(document.body.querySelectorAll("button")).find((el) =>
      el.textContent?.includes("Manage accounts"),
    );
    manage!.click();

    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe("account"));
  });
});
