//
// Bank-account view tests: the account detail page (edit, invite,
// funding, delete) and the create page, against the mock REST API.
//

// 3rd party imports
//
import { flushPromises } from "@vue/test-utils";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

// app imports
//
import App from "@/App.vue";
import { useBankAccountsStore } from "@/stores/bankAccounts";
import { mountWithApp, withAccounts, withAuth } from "../helpers";
import {
  makeBank,
  makeBankAccount,
  makeFundingRunResult,
  makeFundingSummary,
  makePage,
  makeUser,
} from "../mocks/factories";
import { requestsTo, server } from "../mocks/server";

////////////////////////////////////////////////////////////////////////
//
type Wrapper = Awaited<ReturnType<typeof mountWithApp>>["wrapper"];

function button(wrapper: Wrapper, text: string) {
  return wrapper.findAll("button").find((b) => b.text().trim() === text)!;
}

function dialogButton(text: string) {
  return Array.from(
    document.body.querySelectorAll('[role="dialog"] button'),
  ).find((b) => b.textContent?.trim() === text) as HTMLButtonElement;
}

////////////////////////////////////////////////////////////////////////
//
describe("BankAccountDetailView", () => {
  let account: ReturnType<typeof makeBankAccount>;

  beforeEach(() => {
    withAuth(undefined, makeUser({ email: "owner@example.com" }));
    account = makeBankAccount({
      name: "Household",
      account_number: "123456789",
    });
    withAccounts([account]);
    server.use(
      http.get(`/api/v1/bank-accounts/${account.id}/`, () =>
        HttpResponse.json(account),
      ),
      http.get(`/api/v1/banks/${account.bank}/`, () =>
        HttpResponse.json(
          makeBank({ id: account.bank, name: "Bank of Testing" }),
        ),
      ),
    );
  });

  async function open() {
    const mounted = await mountWithApp(App, {
      route: `/account/bank-accounts/${account.id}/`,
    });
    await vi.waitFor(() =>
      expect(mounted.wrapper.find("h1").exists()).toBe(true),
    );
    await flushPromises();
    return mounted;
  }

  // GIVEN: an account on the server
  // WHEN:  its page opens
  // THEN:  name, type, bank and masked number are shown
  //
  it("shows the account", async () => {
    const { wrapper } = await open();
    expect(wrapper.get("h1").text()).toBe("Household");
    expect(wrapper.text()).toMatch(/Checking\s*·\s*Bank of Testing/);
    expect(wrapper.text()).toContain("····6789");
  });

  // GIVEN: the account page
  // WHEN:  the user renames the account
  // THEN:  the PATCH is sent and the bank-accounts cache (and so the
  //        top bar) shows the new name
  //
  it("renames the account", async () => {
    const { wrapper } = await open();
    await wrapper.get('button[aria-label="Edit account"]').trigger("click");
    await wrapper.get("#edit-name").setValue("Joint");
    await button(wrapper, "Save").trigger("click");
    await flushPromises();

    const [patch] = await requestsTo(
      "PATCH",
      `/api/v1/bank-accounts/${account.id}/`,
    );
    expect(patch.body).toEqual({ name: "Joint" });
    expect(useBankAccountsStore().byId(account.id)?.name).toBe("Joint");
  });

  // GIVEN: the invite form
  // WHEN:  the user invites an address that is already invited (409)
  // THEN:  the conflict message is shown
  //
  it("explains a conflicting invitation", async () => {
    server.use(
      http.post(`/api/v1/bank-accounts/${account.id}/invite/`, () =>
        HttpResponse.json({ detail: "conflict" }, { status: 409 }),
      ),
    );
    const { wrapper } = await open();

    await button(wrapper, "+ Invite co-owner").trigger("click");
    await wrapper.get("#invite-email").setValue("Friend@Example.com");
    await button(wrapper, "Review").trigger("click");
    dialogButton("Send invitation").click();
    await flushPromises();

    const [post] = await requestsTo(
      "POST",
      `/api/v1/bank-accounts/${account.id}/invite/`,
    );
    expect(post.body).toEqual({ invitee_email: "friend@example.com" });
    expect(wrapper.text()).toContain("already an owner");
  });

  // GIVEN: an empty invite form
  // WHEN:  the user reviews it
  // THEN:  it asks for an address and sends nothing
  //
  it("requires an invite address", async () => {
    const { wrapper } = await open();
    await button(wrapper, "+ Invite co-owner").trigger("click");
    await button(wrapper, "Review").trigger("click");
    expect(wrapper.text()).toContain("Email address is required.");
  });

  // GIVEN: a pending invitation the user sent
  // WHEN:  they cancel it
  // THEN:  the cancel request is sent and the row disappears
  //
  it("cancels a pending invitation", async () => {
    const { wrapper } = await open();
    await vi.waitFor(() =>
      expect(wrapper.text()).toContain("invitee@example.com"),
    );
    await button(wrapper, "Cancel").trigger("click");
    await flushPromises();
    expect(wrapper.text()).not.toContain("invitee@example.com");
  });

  // GIVEN: a funding event due
  // WHEN:  the user runs funding
  // THEN:  the result is shown and the account and its budgets are
  //        refetched
  //
  it("runs funding and refreshes balances", async () => {
    server.use(
      http.get(`/api/v1/bank-accounts/${account.id}/funding-summary/`, () =>
        HttpResponse.json(makeFundingSummary({ total_amount: "40.00" })),
      ),
      http.post(`/api/v1/bank-accounts/${account.id}/run-funding/`, () =>
        HttpResponse.json(
          makeFundingRunResult({ transfers: 2, warnings: ["Rent short"] }),
        ),
      ),
    );
    const { wrapper } = await open();
    expect(wrapper.text()).toContain("Next event:");

    await button(wrapper, "Run funding now").trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("2 transfers completed.");
    expect(wrapper.text()).toContain("Rent short");
    expect(
      (await requestsTo("GET", `/api/v1/bank-accounts/${account.id}/`)).length,
    ).toBeGreaterThanOrEqual(2);
    expect(await requestsTo("GET", "/api/v1/budgets/")).not.toHaveLength(0);
  });

  // GIVEN: automatic funding on
  // WHEN:  the user switches it off
  // THEN:  the PATCH is sent
  //
  it("toggles automatic funding", async () => {
    const { wrapper } = await open();
    await wrapper.get('input[type="checkbox"]').trigger("change");
    await flushPromises();
    const [patch] = await requestsTo(
      "PATCH",
      `/api/v1/bank-accounts/${account.id}/`,
    );
    expect(patch.body).toEqual({ auto_funding_enabled: false });
  });

  // GIVEN: automatic funding on, and a first toggle's request in flight
  // WHEN:  the user toggles again, then the first request finishes
  // THEN:  the switch keeps showing the second choice until its own
  //        request finishes, and the server ends with that choice
  //
  it("keeps the latest toggle while an earlier one finishes", async () => {
    const gates: (() => void)[] = [];
    server.use(
      http.patch(
        `/api/v1/bank-accounts/${account.id}/`,
        async ({ request }) => {
          const body = (await request.json()) as Record<string, unknown>;
          await new Promise<void>((release) => gates.push(release));
          return HttpResponse.json({ ...account, ...body });
        },
      ),
    );
    const { wrapper } = await open();
    const toggle = wrapper.get('input[type="checkbox"]');

    await toggle.trigger("change");
    await toggle.trigger("change");
    await vi.waitFor(() => expect(gates.length).toBeGreaterThanOrEqual(1));
    gates[0]();
    await flushPromises();

    expect((toggle.element as HTMLInputElement).checked).toBe(true);

    await vi.waitFor(() => expect(gates).toHaveLength(2));
    gates[1]();
    await flushPromises();

    expect((toggle.element as HTMLInputElement).checked).toBe(true);
    const patches = await requestsTo(
      "PATCH",
      `/api/v1/bank-accounts/${account.id}/`,
    );
    expect(patches.map((p) => p.body)).toEqual([
      { auto_funding_enabled: false },
      { auto_funding_enabled: true },
    ]);
  });

  // GIVEN: the account page
  // WHEN:  the user confirms delete
  // THEN:  the account is deleted and the Account tab opens
  //
  it("deletes the account", async () => {
    server.use(
      http.get("/api/v1/bank-accounts/", () => HttpResponse.json(makePage([]))),
    );
    const { wrapper, router } = await open();

    await button(wrapper, "Delete account").trigger("click");
    dialogButton("Delete account").click();
    await flushPromises();

    expect(
      await requestsTo("DELETE", `/api/v1/bank-accounts/${account.id}/`),
    ).toHaveLength(1);
    await vi.waitFor(() =>
      expect(router.currentRoute.value.name).toBe("account"),
    );
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("BankAccountCreateView", () => {
  // GIVEN: the new-account form with a bank list
  // WHEN:  the user fills it in and submits
  // THEN:  the account is created with decimal balances and its page opens
  //
  it("creates an account", async () => {
    withAuth();
    withAccounts([makeBankAccount()]);
    const bank = makeBank({ name: "Bank of Testing" });
    server.use(
      http.get("/api/v1/banks/", () => HttpResponse.json(makePage([bank]))),
    );
    const { wrapper, router } = await mountWithApp(App, {
      route: "/account/bank-accounts/create/",
    });
    await vi.waitFor(() =>
      expect(wrapper.find("#acct-bank").exists()).toBe(true),
    );

    await wrapper.get("#acct-name").setValue("Savings");
    await wrapper.get("#acct-bank").setValue(bank.id);
    await wrapper.get("#acct-number").setValue("5555");
    await wrapper.get("#acct-posted").setValue("100.5");
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    const [post] = await requestsTo("POST", "/api/v1/bank-accounts/");
    expect(post.body).toEqual({
      account_type: "C",
      name: "Savings",
      bank: bank.id,
      currency: "USD",
      account_number: "5555",
      posted_balance: "100.50",
    });
    await vi.waitFor(() =>
      expect(router.currentRoute.value.name).toBe("bank-account-detail"),
    );
  });

  // GIVEN: a form with no name
  // WHEN:  it is submitted
  // THEN:  it is refused before any request
  //
  it("requires a name", async () => {
    withAuth();
    withAccounts([makeBankAccount()]);
    const { wrapper } = await mountWithApp(App, {
      route: "/account/bank-accounts/create/",
    });
    await vi.waitFor(() => expect(wrapper.find("form").exists()).toBe(true));
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(wrapper.text()).toContain("Account name is required.");
    expect(await requestsTo("POST", "/api/v1/bank-accounts/")).toHaveLength(0);
  });
});
