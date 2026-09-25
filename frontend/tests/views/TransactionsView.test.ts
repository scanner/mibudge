//
// TransactionsView tests: the list through the real router, stores, API
// modules and transport, with only the network mocked.
//

// 3rd party imports
//
import { flushPromises } from "@vue/test-utils";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

// app imports
//
import { useAccountContextStore } from "@/stores/accountContext";
import { useTransactionNavStore } from "@/stores/transactionNav";
import TransactionsView from "@/views/TransactionsView.vue";
import { mountWithApp, withAccounts, withAuth } from "../helpers";
import { makeBankAccount, makePage, makeTransaction } from "../mocks/factories";
import { server } from "../mocks/server";

////////////////////////////////////////////////////////////////////////
//
describe("TransactionsView", () => {
  beforeEach(() => {
    withAuth();
  });

  // GIVEN: a list with posted and pending transactions
  // WHEN:  the "Pending" filter chip is selected
  // THEN:  only pending rows are shown
  //  AND:  the detail view's previous / next walk only those rows
  //
  it("previous / next follow the active filter", async () => {
    const account = makeBankAccount();
    withAccounts([account]);
    const [t1, t2, t3] = [
      makeTransaction({ bank_account: account.id, party: "Posted one", pending: false }),
      makeTransaction({ bank_account: account.id, party: "Pending one", pending: true }),
      makeTransaction({ bank_account: account.id, party: "Posted two", pending: false }),
    ];
    server.use(http.get("/api/v1/transactions/", () => HttpResponse.json(makePage([t1, t2, t3]))));
    const { wrapper } = await mountWithApp(TransactionsView, { route: "/transactions/" });
    await vi.waitFor(() => expect(wrapper.text()).toContain("Posted two"));

    await wrapper
      .findAll("button")
      .find((b) => b.text() === "Pending")!
      .trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("Pending one");
    expect(wrapper.text()).not.toContain("Posted one");
    expect(useTransactionNavStore().orderedIds).toEqual([t2.id]);
  });

  // GIVEN: account A's transactions still loading
  // WHEN:  the user switches to account B, whose list answers first
  // THEN:  B's transactions are shown and A's late answer is ignored
  //
  it("ignores a response for the previous account", async () => {
    const [a, b] = [makeBankAccount(), makeBankAccount()];
    withAccounts([a, b], a.id);
    let releaseA!: () => void;
    const gateA = new Promise<void>((resolve) => (releaseA = resolve));
    server.use(
      http.get("/api/v1/transactions/", async ({ request }) => {
        const accountId = new URL(request.url).searchParams.get("bank_account");
        if (accountId === a.id) {
          await gateA;
          return HttpResponse.json(makePage([makeTransaction({ party: "From account A" })]));
        }
        return HttpResponse.json(makePage([makeTransaction({ party: "From account B" })]));
      }),
    );
    const { wrapper } = await mountWithApp(TransactionsView, { route: "/transactions/" });

    useAccountContextStore().setActive(b.id);
    await vi.waitFor(() => expect(wrapper.text()).toContain("From account B"));
    releaseA();
    await flushPromises();
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(wrapper.text()).toContain("From account B");
    expect(wrapper.text()).not.toContain("From account A");
  });

  // GIVEN: a list loaded for the active account
  // WHEN:  the user searches for a party
  // THEN:  only matching rows are shown, and the query is remembered
  //
  it("filters rows by search", async () => {
    const account = makeBankAccount();
    withAccounts([account]);
    server.use(
      http.get("/api/v1/transactions/", ({ request }) => {
        const search = new URL(request.url).searchParams.get("search");
        return HttpResponse.json(
          makePage(
            search
              ? []
              : [
                  makeTransaction({ bank_account: account.id, party: "Blue Bottle" }),
                  makeTransaction({ bank_account: account.id, party: "Hardware Store" }),
                ],
          ),
        );
      }),
    );
    const { wrapper } = await mountWithApp(TransactionsView, { route: "/transactions/" });
    await vi.waitFor(() => expect(wrapper.text()).toContain("Hardware Store"));

    await wrapper.get('button[aria-label="Search transactions"]').trigger("click");
    await wrapper.get('input[placeholder="Search transactions…"]').setValue("bottle");

    await vi.waitFor(() => expect(wrapper.text()).not.toContain("Hardware Store"));
    expect(wrapper.text()).toContain("Blue Bottle");
    expect(useTransactionNavStore().savedSearch).toBe("bottle");
  });

  // GIVEN: the transaction list endpoint fails
  // WHEN:  the view opens
  // THEN:  the error message is shown
  //
  it("shows the error state", async () => {
    withAccounts([makeBankAccount()]);
    server.use(http.get("/api/v1/transactions/", () => new HttpResponse(null, { status: 500 })));

    const { wrapper } = await mountWithApp(TransactionsView, { route: "/transactions/" });

    await vi.waitFor(() => expect(wrapper.text()).toContain("HTTP 500"));
  });
});
