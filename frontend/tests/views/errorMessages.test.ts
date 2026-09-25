//
// Error-message tests: every load or action that fails shows the
// server's reason, through the real router, stores, API modules and
// transport with only the network mocked.  Each case answers one
// endpoint with a DRF error body carrying a distinctive message and
// checks that message reaches the page.
//

// 3rd party imports
//
import { flushPromises } from "@vue/test-utils";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

// app imports
//
import App from "@/App.vue";
import type { BankAccountDto } from "@/api/dto";
import { useTransactionNavStore } from "@/stores/transactionNav";
import { mountWithApp, withAccounts, withAuth } from "../helpers";
import {
  makeAllocation,
  makeApiKey,
  makeBankAccount,
  makeBudget,
  makePage,
  makeTransaction,
  makeUser,
} from "../mocks/factories";
import { server } from "../mocks/server";

////////////////////////////////////////////////////////////////////////
//
type Wrapper = Awaited<ReturnType<typeof mountWithApp>>["wrapper"];

const AUTOSAVE_WAIT_MS = 900;

function refuse(message: string, status = 400) {
  return () => HttpResponse.json({ detail: message }, { status });
}

// The "Cancel" button in the list row that shows `email`.
//
function rowCancel(wrapper: Wrapper, email: string) {
  const row = wrapper.findAll("li").find((li) => li.text().includes(email));
  if (!row) throw new Error(`no row for ${email}`);
  return row.findAll("button").find((b) => b.text().trim() === "Cancel")!;
}

function button(wrapper: Wrapper, text: string) {
  const found = wrapper.findAll("button").find((b) => b.text().trim() === text);
  if (!found) throw new Error(`no button "${text}"`);
  return found;
}

// A button inside a teleported sheet or dialog.
//
function bodyButton(text: string, within = "body") {
  const found = Array.from(document.body.querySelectorAll(`${within} button`)).find(
    (b) => b.textContent?.trim() === text,
  ) as HTMLButtonElement | undefined;
  if (!found) throw new Error(`no body button "${text}"`);
  return found;
}

async function open(path: string) {
  const mounted = await mountWithApp(App, { route: path });
  await vi.waitFor(() => expect(mounted.wrapper.find("main").exists()).toBe(true));
  await flushPromises();
  return mounted;
}

let account: BankAccountDto;

beforeEach(() => {
  withAuth(undefined, makeUser({ email: "owner@example.com" }));
  account = makeBankAccount({ name: "Household" });
  withAccounts([account]);
  server.use(http.get("/api/v1/bank-accounts/", () => HttpResponse.json(makePage([account]))));
});

////////////////////////////////////////////////////////////////////////
//
describe("budget pages", () => {
  function serveBudget(budget: ReturnType<typeof makeBudget>) {
    server.use(
      http.get(`/api/v1/budgets/${budget.id}/`, () => HttpResponse.json(budget)),
      http.get("/api/v1/budgets/", () => HttpResponse.json(makePage([budget]))),
      http.get("/api/v1/allocations/", () => HttpResponse.json(makePage([]))),
    );
  }

  // GIVEN: a budget id the server does not know
  // WHEN:  its page opens
  // THEN:  the server's reason is shown, not a generic load failure
  //
  it("shows why a budget failed to load", async () => {
    server.use(http.get("/api/v1/budgets/:id/", refuse("No such budget.", 404)));

    const { wrapper } = await open("/budgets/missing/");

    await vi.waitFor(() => expect(wrapper.text()).toContain("No such budget."));
  });

  // GIVEN: a budget the server refuses to pause
  // WHEN:  the user pauses it
  // THEN:  the server's reason is shown
  //
  it("shows why a pause failed", async () => {
    const budget = makeBudget({ name: "Groceries", bank_account: account.id });
    serveBudget(budget);
    server.use(http.patch(`/api/v1/budgets/${budget.id}/`, refuse("Budget is locked.")));
    const { wrapper } = await open(`/budgets/${budget.id}/`);

    await button(wrapper, "Pause budget").trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("Budget is locked.");
  });

  // GIVEN: two budgets and a transfer the server refuses
  // WHEN:  the user moves money between them
  // THEN:  the server's reason is shown in the sheet
  //
  it("shows why a transfer failed", async () => {
    const budget = makeBudget({ name: "Groceries", bank_account: account.id });
    const other = makeBudget({ name: "Rent", bank_account: account.id });
    serveBudget(budget);
    server.use(
      http.get("/api/v1/budgets/", () => HttpResponse.json(makePage([budget, other]))),
      http.post("/api/v1/internal-transactions/", () =>
        HttpResponse.json({ amount: ["Rent has only $5.00."] }, { status: 400 }),
      ),
    );
    const { wrapper } = await open(`/budgets/${budget.id}/`);

    await wrapper
      .findAll("button")
      .find((b) => b.text().includes("Move money"))!
      .trigger("click");
    await flushPromises();
    const amount = document.body.querySelector<HTMLInputElement>('input[placeholder="0.00"]')!;
    amount.value = "20";
    amount.dispatchEvent(new Event("input"));
    await flushPromises();
    bodyButton("Transfer").click();
    await flushPromises();

    expect(document.body.textContent).toContain("Rent has only $5.00.");
  });

  // GIVEN: a budget whose transactions fail to load
  // WHEN:  its page opens
  // THEN:  the server's reason is shown instead of "no transactions"
  //
  it("shows why the budget's transactions failed to load", async () => {
    const budget = makeBudget({ name: "Groceries", bank_account: account.id });
    serveBudget(budget);
    server.use(http.get("/api/v1/allocations/", refuse("Allocations are unavailable.", 503)));

    const { wrapper } = await open(`/budgets/${budget.id}/`);

    await vi.waitFor(() => expect(wrapper.text()).toContain("Allocations are unavailable."));
    expect(wrapper.text()).not.toContain("No transactions assigned");
  });

  // GIVEN: a transaction assigned to the budget, and a split the
  //        server refuses
  // WHEN:  the user removes the transaction from the budget
  // THEN:  the server's reason is shown and the row stays
  //
  it("shows why removing a transaction failed", async () => {
    const budget = makeBudget({ name: "Groceries", bank_account: account.id });
    const tx = makeTransaction({ bank_account: account.id, party: "Corner Market" });
    serveBudget(budget);
    server.use(
      http.get("/api/v1/allocations/", () =>
        HttpResponse.json(
          makePage([makeAllocation({ transaction: tx.id, budget: budget.id, amount: tx.amount })]),
        ),
      ),
      http.get(`/api/v1/transactions/${tx.id}/`, () => HttpResponse.json(tx)),
      http.post(`/api/v1/transactions/${tx.id}/splits/`, refuse("Transaction is pending.")),
    );
    const { wrapper } = await open(`/budgets/${budget.id}/`);
    await vi.waitFor(() => expect(wrapper.text()).toContain("Corner Market"));

    await wrapper.get('button[aria-label="Remove from budget"]').trigger("click");
    await flushPromises();

    await vi.waitFor(() => expect(wrapper.text()).toContain("Transaction is pending."));
    expect(wrapper.text()).toContain("Corner Market");
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("transaction detail", () => {
  function serveTransaction(tx: ReturnType<typeof makeTransaction>) {
    server.use(
      http.get(`/api/v1/transactions/${tx.id}/`, () => HttpResponse.json(tx)),
      http.get("/api/v1/allocations/", () => HttpResponse.json(makePage([]))),
    );
  }

  // GIVEN: a transaction whose memo edit the server refuses
  // WHEN:  the autosave runs
  // THEN:  the memo reverts and the page says it was not saved, and why
  //
  it("shows why a memo was not saved", async () => {
    const tx = makeTransaction({ bank_account: account.id, memo: "Team lunch", pending: false });
    serveTransaction(tx);
    server.use(
      http.patch(`/api/v1/transactions/${tx.id}/`, () =>
        HttpResponse.json(
          { memo: ["Ensure this field has no more than 5 characters."] },
          {
            status: 400,
          },
        ),
      ),
    );
    const { wrapper } = await open(`/transactions/${tx.id}/`);

    await wrapper.get("textarea").setValue("A much longer memo");
    await new Promise((resolve) => setTimeout(resolve, AUTOSAVE_WAIT_MS));
    await flushPromises();

    expect(wrapper.text()).toContain(
      "Couldn't save the memo: Ensure this field has no more than 5 characters.",
    );
    expect((wrapper.get("textarea").element as HTMLTextAreaElement).value).toBe("Team lunch");
  });

  // GIVEN: a split the server refuses
  // WHEN:  the user assigns the transaction to a budget
  // THEN:  the page says the split was not saved, and why
  //
  it("shows why a split was not saved", async () => {
    const tx = makeTransaction({ bank_account: account.id, amount: "-20.00" });
    const rent = makeBudget({ name: "Rent", bank_account: account.id, budget_type: "R" });
    serveTransaction(tx);
    server.use(
      http.get("/api/v1/budgets/", () => HttpResponse.json(makePage([rent]))),
      http.post(`/api/v1/transactions/${tx.id}/splits/`, () =>
        HttpResponse.json({ splits: ["Splits exceed the transaction amount."] }, { status: 400 }),
      ),
    );
    const { wrapper } = await open(`/transactions/${tx.id}/`);

    await wrapper
      .findAll("button")
      .find((b) => b.text().includes("Assign to budget"))!
      .trigger("click");
    const select = document.body.querySelector<HTMLSelectElement>(".split-row-select")!;
    select.value = rent.id;
    select.dispatchEvent(new Event("change"));
    await flushPromises();
    bodyButton("Save").click();
    await flushPromises();

    expect(wrapper.text()).toContain(
      "Couldn't save the split: Splits exceed the transaction amount.",
    );
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("transaction list", () => {
  // GIVEN: a list whose second page fails once
  // WHEN:  the user scrolls to the end, then presses "Try again"
  // THEN:  the server's reason is shown with a retry, and the retry
  //        appends the page
  //
  it("shows why the next page failed and retries", async () => {
    let failNext = true;
    server.use(
      http.get("/api/v1/transactions/", ({ request }) => {
        if (new URL(request.url).searchParams.get("page") === "2") {
          if (failNext) {
            failNext = false;
            return HttpResponse.json({ detail: "Try again shortly." }, { status: 503 });
          }
          return HttpResponse.json(
            makePage([makeTransaction({ bank_account: account.id, party: "Older one" })]),
          );
        }
        return HttpResponse.json(
          makePage([makeTransaction({ bank_account: account.id, party: "Newest" })], {
            next: "http://localhost/api/v1/transactions/?page=2",
          }),
        );
      }),
      http.get("/api/v1/allocations/", () => HttpResponse.json(makePage([]))),
    );
    const { wrapper } = await open("/transactions/");
    await vi.waitFor(() => expect(wrapper.text()).toContain("Newest"));

    // No IntersectionObserver in happy-dom; changing the filter asks for
    // the next page the way reaching the sentinel does.
    useTransactionNavStore().savedFilter = "";
    await button(wrapper, "Pending").trigger("click");
    await button(wrapper, "All").trigger("click");
    await vi.waitFor(() =>
      expect(wrapper.text()).toContain("Couldn't load more transactions: Try again shortly."),
    );

    await button(wrapper, "Try again").trigger("click");
    await vi.waitFor(() => expect(wrapper.text()).toContain("Older one"));
    expect(wrapper.text()).not.toContain("Try again shortly.");
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("settings pages", () => {
  // GIVEN: a notification preference the server will not change
  // WHEN:  the user changes it
  // THEN:  the server's reason is shown
  //
  it("shows why a notification preference was refused", async () => {
    server.use(
      http.patch(
        "/api/v1/notification-preferences/:kind/",
        refuse("Security notices cannot be turned off."),
      ),
    );
    const { wrapper } = await open("/account/settings/");
    await vi.waitFor(() => expect(wrapper.text()).toContain("Budget overdrawn"));

    await wrapper.findAll("select").at(-1)!.setValue("off");
    await flushPromises();

    expect(wrapper.text()).toContain("Security notices cannot be turned off.");
  });

  // GIVEN: an API key the server will not revoke
  // WHEN:  the user revokes it
  // THEN:  the server's reason is shown
  //
  it("shows why revoking an API key failed", async () => {
    const key = makeApiKey({ name: "importer" });
    server.use(
      http.get("/api/v1/users/me/api-keys/", () => HttpResponse.json(makePage([key]))),
      http.post(
        `/api/v1/users/me/api-keys/${key.uuid}/revoke/`,
        refuse("Key is in use by a running import.", 409),
      ),
    );
    const { wrapper } = await open("/account/settings/");
    await vi.waitFor(() => expect(wrapper.text()).toContain("importer"));

    await button(wrapper, "Revoke").trigger("click");
    bodyButton("Revoke", '[role="dialog"]').click();
    await flushPromises();

    expect(wrapper.text()).toContain("Key is in use by a running import.");
  });

  // GIVEN: a sent invitation the server will not cancel
  // WHEN:  the user cancels it from the settings page
  // THEN:  the server's reason is shown and the row stays
  //
  it("shows why cancelling a sent invitation failed", async () => {
    server.use(
      http.post(
        "/api/v1/bank-accounts/:id/invitations/:token/cancel/",
        refuse("Invitation was already accepted.", 409),
      ),
    );
    const { wrapper } = await open("/account/settings/");
    await vi.waitFor(() => expect(wrapper.text()).toContain("invitee@example.com"));

    await rowCancel(wrapper, "invitee@example.com").trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("Invitation was already accepted.");
    expect(wrapper.text()).toContain("invitee@example.com");
  });

  // GIVEN: a default account the server refuses
  // WHEN:  the user picks it on the Account tab
  // THEN:  the server's reason is shown
  //
  it("shows why the default account was not saved", async () => {
    server.use(
      http.patch("/api/v1/users/me/", () =>
        HttpResponse.json(
          { default_bank_account: ["You no longer own this account."] },
          { status: 400 },
        ),
      ),
    );
    const { wrapper } = await open("/account/");

    await wrapper.get("select").setValue(account.id);
    await flushPromises();

    expect(wrapper.text()).toContain("You no longer own this account.");
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("bank-account pages", () => {
  async function openAccount() {
    server.use(http.get(`/api/v1/bank-accounts/${account.id}/`, () => HttpResponse.json(account)));
    const mounted = await open(`/account/bank-accounts/${account.id}/`);
    await vi.waitFor(() => expect(mounted.wrapper.find("h1").exists()).toBe(true));
    return mounted;
  }

  // GIVEN: an automatic-funding change the server refuses
  // WHEN:  the user flips the toggle
  // THEN:  the server's reason is shown
  //
  it("shows why automatic funding did not change", async () => {
    server.use(
      http.patch(`/api/v1/bank-accounts/${account.id}/`, refuse("Funding run in progress.", 409)),
    );
    const { wrapper } = await openAccount();

    await wrapper.get('input[type="checkbox"]').trigger("change");
    await flushPromises();

    expect(wrapper.text()).toContain("Funding run in progress.");
  });

  // GIVEN: an account the server will not delete
  // WHEN:  the user confirms delete
  // THEN:  the server's reason is shown and the page stays
  //
  it("shows why deleting the account failed", async () => {
    server.use(
      http.delete(
        `/api/v1/bank-accounts/${account.id}/`,
        refuse("Only the last owner can delete an account.", 403),
      ),
    );
    const { wrapper, router } = await openAccount();

    await button(wrapper, "Delete account").trigger("click");
    bodyButton("Delete account", '[role="dialog"]').click();
    await flushPromises();

    expect(wrapper.text()).toContain("Only the last owner can delete an account.");
    expect(router.currentRoute.value.name).toBe("bank-account-detail");
  });

  // GIVEN: a pending invitation the server will not cancel
  // WHEN:  the user cancels it on the account page
  // THEN:  the server's reason is shown and the row stays
  //
  it("shows why cancelling a pending invitation failed", async () => {
    server.use(
      http.post(
        "/api/v1/bank-accounts/:id/invitations/:token/cancel/",
        refuse("Invitation was already accepted.", 409),
      ),
    );
    const { wrapper } = await openAccount();
    await vi.waitFor(() => expect(wrapper.text()).toContain("invitee@example.com"));

    await rowCancel(wrapper, "invitee@example.com").trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("Invitation was already accepted.");
    expect(wrapper.text()).toContain("invitee@example.com");
  });

  // GIVEN: the bank list fails to load
  // WHEN:  the new-account page opens
  // THEN:  the server's reason is shown
  //
  it("shows why the bank list failed to load", async () => {
    server.use(http.get("/api/v1/banks/", refuse("Bank directory unavailable.", 503)));

    const { wrapper } = await open("/account/bank-accounts/create/");

    await vi.waitFor(() => expect(wrapper.text()).toContain("Bank directory unavailable."));
  });
});
