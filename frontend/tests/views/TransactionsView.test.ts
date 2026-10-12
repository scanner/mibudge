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
import type { BankAccountDto, BudgetDto } from "@/api/dto";
import { useAccountContextStore } from "@/stores/accountContext";
import { useInvalidationStore } from "@/stores/invalidation";
import { useTransactionNavStore } from "@/stores/transactionNav";
import TransactionsView from "@/views/TransactionsView.vue";
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
      makeTransaction({
        bank_account: account.id,
        party: "Posted one",
        pending: false,
      }),
      makeTransaction({
        bank_account: account.id,
        party: "Pending one",
        pending: true,
      }),
      makeTransaction({
        bank_account: account.id,
        party: "Posted two",
        pending: false,
      }),
    ];
    server.use(
      http.get("/api/v1/transactions/", () =>
        HttpResponse.json(makePage([t1, t2, t3])),
      ),
    );
    const { wrapper } = await mountWithApp(TransactionsView, {
      route: "/transactions/",
    });
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
          return HttpResponse.json(
            makePage([makeTransaction({ party: "From account A" })]),
          );
        }
        return HttpResponse.json(
          makePage([makeTransaction({ party: "From account B" })]),
        );
      }),
    );
    const { wrapper } = await mountWithApp(TransactionsView, {
      route: "/transactions/",
    });

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
                  makeTransaction({
                    bank_account: account.id,
                    party: "Copper Kettle Coffee",
                  }),
                  makeTransaction({
                    bank_account: account.id,
                    party: "Hardware Store",
                  }),
                ],
          ),
        );
      }),
    );
    const { wrapper } = await mountWithApp(TransactionsView, {
      route: "/transactions/",
    });
    await vi.waitFor(() => expect(wrapper.text()).toContain("Hardware Store"));

    await wrapper
      .get('button[aria-label="Search transactions"]')
      .trigger("click");
    await wrapper
      .get('input[placeholder="Search transactions…"]')
      .setValue("kettle");

    await vi.waitFor(() =>
      expect(wrapper.text()).not.toContain("Hardware Store"),
    );
    expect(wrapper.text()).toContain("Copper Kettle Coffee");
    expect(useTransactionNavStore().savedSearch).toBe("kettle");
  });

  // GIVEN: the transaction list endpoint fails
  // WHEN:  the view opens
  // THEN:  the error message is shown
  //
  it("shows the error state", async () => {
    withAccounts([makeBankAccount()]);
    server.use(
      http.get(
        "/api/v1/transactions/",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );

    const { wrapper } = await mountWithApp(TransactionsView, {
      route: "/transactions/",
    });

    await vi.waitFor(() => expect(wrapper.text()).toContain("HTTP 500"));
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("TransactionsView background refresh", () => {
  beforeEach(() => {
    withAuth();
  });

  // GIVEN: a list scrolled two pages deep
  // WHEN:  a new transaction arrives on the server and the page
  //        refreshes in the background
  // THEN:  the loaded rows stay on screen (no loading skeleton) while
  //        it runs
  //  AND:  afterwards the new row is on top and every loaded row is
  //        still listed
  //
  it("refreshes a scrolled list in place", async () => {
    const account = makeBankAccount();
    withAccounts([account]);
    const tx = (party: string, date: string) =>
      makeTransaction({
        bank_account: account.id,
        party,
        transaction_date: date,
      });
    let rows = [
      tx("Older", "2026-10-02T12:00:00Z"),
      tx("Oldest", "2026-10-01T12:00:00Z"),
    ];
    let gate: Promise<void> = Promise.resolve();
    // One row per page, except when the refresh asks for a page size.
    server.use(
      http.get("/api/v1/transactions/", async ({ request }) => {
        const url = new URL(request.url);
        if (url.searchParams.has("page_size")) {
          await gate;
          return HttpResponse.json(makePage(rows));
        }
        const n = Number(url.searchParams.get("page") ?? "1");
        const next =
          n < rows.length
            ? `http://localhost/api/v1/transactions/?bank_account=${account.id}&page=${n + 1}`
            : null;
        return HttpResponse.json(makePage([rows[n - 1]], { next }));
      }),
    );
    const { wrapper } = await mountWithApp(TransactionsView, {
      route: "/transactions/",
    });
    await vi.waitFor(() => expect(wrapper.text()).toContain("Older"));
    // No IntersectionObserver in happy-dom; changing the filter asks for
    // the next page the way reaching the sentinel does.
    const chip = (label: string) =>
      wrapper.findAll("button").find((b) => b.text() === label)!;
    await chip("Pending").trigger("click");
    await chip("All").trigger("click");
    await vi.waitFor(() => expect(wrapper.text()).toContain("Oldest"));

    rows = [tx("Newest", "2026-10-03T12:00:00Z"), ...rows];
    let release!: () => void;
    gate = new Promise<void>((resolve) => (release = resolve));
    const refresh = useInvalidationStore().invalidate({
      bankAccountId: account.id,
      kinds: ["transactions"],
    });
    await flushPromises();
    expect
      .soft(wrapper.find(".animate-pulse").exists(), "no skeleton")
      .toBe(false);
    expect.soft(wrapper.text(), "rows stay meanwhile").toContain("Oldest");
    release();
    await refresh;
    await flushPromises();

    const text = wrapper.text();
    expect.soft(text, "new row").toContain("Newest");
    expect
      .soft(text.indexOf("Newest") < text.indexOf("Older"), "on top")
      .toBe(true);
    expect.soft(text, "loaded rows kept").toContain("Oldest");
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("TransactionsView budget assignments", () => {
  let account: BankAccountDto;
  let groceries: BudgetDto;
  let rent: BudgetDto;

  beforeEach(() => {
    withAuth();
    account = makeBankAccount();
    withAccounts([account]);
    groceries = makeBudget({ name: "Groceries", bank_account: account.id });
    rent = makeBudget({ name: "Rent", bank_account: account.id });
    server.use(
      http.get("/api/v1/budgets/", () =>
        HttpResponse.json(makePage([groceries, rent])),
      ),
    );
  });

  function allocatedTo(budget: BudgetDto, party = "Corner Market") {
    return makeTransaction({
      bank_account: account.id,
      party,
      allocations: [makeAllocation({ budget: budget.id })],
    });
  }

  // GIVEN: the list was visited with a transaction assigned to Groceries
  // WHEN:  the transaction is re-assigned to Rent elsewhere (a co-owner,
  //        or a sync) and the list is visited again
  // THEN:  the list shows Rent, from the transactions it reloaded
  //
  it("shows each visit's budget assignments", async () => {
    server.use(
      http.get("/api/v1/transactions/", () =>
        HttpResponse.json(makePage([allocatedTo(groceries)])),
      ),
    );
    const first = await mountWithApp(TransactionsView, {
      route: "/transactions/",
    });
    await vi.waitFor(() => expect(first.wrapper.text()).toContain("Groceries"));
    first.wrapper.unmount();

    server.use(
      http.get("/api/v1/transactions/", () =>
        HttpResponse.json(makePage([allocatedTo(rent)])),
      ),
    );
    const second = await mountWithApp(TransactionsView, {
      route: "/transactions/",
    });

    await vi.waitFor(() => expect(second.wrapper.text()).toContain("Rent"));
    expect(second.wrapper.text()).not.toContain("Groceries");
  });

  // GIVEN: a list with assigned and unassigned transactions
  // WHEN:  the "Unallocated" chip is selected, then "All"
  // THEN:  the list is reloaded with `unallocated=true` and shows the
  //        server's matches, then reloaded without it
  //
  it("asks the server for unallocated transactions", async () => {
    const assigned = allocatedTo(groceries, "Assigned Shop");
    const unassigned = makeTransaction({
      bank_account: account.id,
      party: "Unassigned Shop",
    });
    server.use(
      http.get("/api/v1/transactions/", ({ request }) => {
        const params = new URL(request.url).searchParams;
        return HttpResponse.json(
          makePage(
            params.get("unallocated") === "true"
              ? [unassigned]
              : [assigned, unassigned],
          ),
        );
      }),
    );
    const { wrapper } = await mountWithApp(TransactionsView, {
      route: "/transactions/",
    });
    await vi.waitFor(() => expect(wrapper.text()).toContain("Assigned Shop"));
    const chip = (label: string) =>
      wrapper.findAll("button").find((b) => b.text() === label)!;

    await chip("Unallocated").trigger("click");
    await vi.waitFor(() => {
      expect(wrapper.text()).toContain("Unassigned Shop");
      expect(wrapper.text()).not.toContain("Assigned Shop");
    });

    await chip("All").trigger("click");
    await vi.waitFor(() => expect(wrapper.text()).toContain("Assigned Shop"));
    const lists = await requestsTo("GET", "/api/v1/transactions/");
    expect(
      lists.map((r) => new URL(r.url).searchParams.get("unallocated")),
    ).toEqual([null, "true", null]);
  });
});
