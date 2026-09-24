//
// TopBar tests: the account-context header.  One test stubs store
// actions with `createTestingPinia` to check what TopBar asks the
// budgets store for; the other runs the real stores against the mock
// REST API.
//

// 3rd party imports
//
import { createTestingPinia } from "@pinia/testing";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

// app imports
//
import TopBar from "@/components/layout/TopBar.vue";
import { useAccountContextStore } from "@/stores/accountContext";
import { useBudgetsStore } from "@/stores/budgets";
import { mountWithApp, withAuth } from "../helpers";
import { makeBankAccount, makeBudget } from "../mocks/factories";
import { requestsTo, server } from "../mocks/server";

////////////////////////////////////////////////////////////////////////
//
describe("TopBar", () => {
  // GIVEN: an active account whose unallocated budget is not cached
  // WHEN:  the top bar renders
  // THEN:  it shows the account name and a placeholder for the
  //        unallocated amount
  //  AND:  it asks the budgets store to fetch the unallocated budget
  //
  it("requests the unallocated budget for the active account", async () => {
    const account = makeBankAccount({ name: "Household" });
    // Stubbed actions record calls without touching the network.
    const pinia = createTestingPinia({
      createSpy: vi.fn,
      initialState: {
        auth: { accessToken: "t" },
        accountContext: { accounts: [account], activeBankAccountId: account.id },
      },
    });

    const { wrapper } = await mountWithApp(TopBar, { route: "/budgets/", pinia });

    expect(wrapper.text()).toContain("Household, Available:");
    expect(wrapper.text()).toContain("—");
    expect(useBudgetsStore(pinia).fetchOne).toHaveBeenCalledWith(account.unallocated_budget);
  });

  // GIVEN: an active account and its unallocated budget on the server
  // WHEN:  the top bar renders
  // THEN:  the unallocated balance from the API is shown
  //
  it("shows the unallocated balance fetched from the API", async () => {
    withAuth();
    const account = makeBankAccount();
    const unallocated = makeBudget({ id: account.unallocated_budget, balance: "42.50" });
    server.use(
      http.get(`/api/v1/budgets/${unallocated.id}/`, () => HttpResponse.json(unallocated)),
    );
    const ctx = useAccountContextStore();
    ctx.accounts = [account];
    ctx.setActive(account.id);

    const { wrapper } = await mountWithApp(TopBar, { route: "/budgets/" });

    expect(wrapper.text()).toContain("42.50");
    expect(await requestsTo("GET", `/api/v1/budgets/${unallocated.id}/`)).toHaveLength(1);
  });
});
