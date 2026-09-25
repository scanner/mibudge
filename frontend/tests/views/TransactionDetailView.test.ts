//
// TransactionDetailView tests: the app rendered at
// `/transactions/<id>/` through the real router, stores, API modules
// and transport, with only the network mocked.  Covers autosave, memo
// clearing, attachment errors, splits, and previous / next.
//

// 3rd party imports
//
import { flushPromises } from "@vue/test-utils";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// app imports
//
import App from "@/App.vue";
import { useTransactionNavStore } from "@/stores/transactionNav";
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
const AUTOSAVE_WAIT_MS = 900;

function wait(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Serve each transaction in `txs` at its detail URL, with PATCH echoing
// the submitted JSON fields.
//
function serveTransactions(txs: ReturnType<typeof makeTransaction>[]) {
  const byId = new Map(txs.map((t) => [t.id, t]));
  server.use(
    http.get("/api/v1/transactions/:id/", ({ params }) =>
      HttpResponse.json(byId.get(String(params.id)) ?? makeTransaction({ id: String(params.id) })),
    ),
    http.patch("/api/v1/transactions/:id/", async ({ params, request }) => {
      const base = byId.get(String(params.id))!;
      const type = request.headers.get("Content-Type") ?? "";
      const body = type.includes("json") ? ((await request.json()) as object) : {};
      return HttpResponse.json({ ...base, ...body });
    }),
    http.get("/api/v1/allocations/", () => HttpResponse.json(makePage([]))),
  );
}

async function openApp(path: string) {
  const mounted = await mountWithApp(App, { route: path });
  await vi.waitFor(() => expect(mounted.wrapper.find("h1").exists()).toBe(true));
  await flushPromises();
  return mounted;
}

////////////////////////////////////////////////////////////////////////
//
describe("TransactionDetailView", () => {
  let account: ReturnType<typeof makeBankAccount>;

  beforeEach(() => {
    withAuth();
    account = makeBankAccount();
    withAccounts([account]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // GIVEN: the detail view of transaction A with an edited description
  //        not yet saved
  // WHEN:  the user moves to transaction B before the autosave delay
  //        ends
  // THEN:  A's text is saved to A at once, and never written to B
  //
  it("does not save one transaction's text onto the next", async () => {
    const a = makeTransaction({ bank_account: account.id, description: "Coffee" });
    const b = makeTransaction({ bank_account: account.id, description: "Rent" });
    serveTransactions([a, b]);
    // B's detail answers only after the autosave delay, so the pending
    // save for A would fire while B is loading.
    let releaseB!: () => void;
    const gateB = new Promise<void>((resolve) => (releaseB = resolve));
    server.use(
      http.get(`/api/v1/transactions/${b.id}/`, async () => {
        await gateB;
        return HttpResponse.json(b);
      }),
    );
    const { wrapper, router } = await openApp(`/transactions/${a.id}/`);

    const input = wrapper.get('input[type="text"]');
    await input.setValue("Coffee with Sam");
    await router.push(`/transactions/${b.id}/`);
    await flushPromises();
    await wait(AUTOSAVE_WAIT_MS);
    releaseB();
    await flushPromises();

    expect(await requestsTo("PATCH", `/api/v1/transactions/${b.id}/`)).toHaveLength(0);
    const patchesToA = await requestsTo("PATCH", `/api/v1/transactions/${a.id}/`);
    expect(patchesToA.map((r) => r.body)).toEqual([{ description: "Coffee with Sam" }]);
    expect((wrapper.get('input[type="text"]').element as HTMLInputElement).value).toBe("Rent");
  });

  // GIVEN: a transaction with a memo
  // WHEN:  the user clears the memo and the autosave delay passes
  // THEN:  the PATCH sends `memo: null`, clearing it on the server
  //
  it("saves a cleared memo", async () => {
    const tx = makeTransaction({ bank_account: account.id, memo: "Team lunch" });
    serveTransactions([tx]);
    const { wrapper } = await openApp(`/transactions/${tx.id}/`);

    await wrapper.get("textarea").setValue("");
    await wait(AUTOSAVE_WAIT_MS);

    const [patch] = await requestsTo("PATCH", `/api/v1/transactions/${tx.id}/`);
    expect(patch?.body).toEqual({ memo: null });
  });

  // GIVEN: a description edit
  // WHEN:  the field loses focus before the autosave delay
  // THEN:  it is saved at once
  //
  it("saves the description on blur", async () => {
    const tx = makeTransaction({ bank_account: account.id, description: "Coffee" });
    serveTransactions([tx]);
    const { wrapper } = await openApp(`/transactions/${tx.id}/`);

    const input = wrapper.get('input[type="text"]');
    await input.setValue("Coffee beans");
    await input.trigger("blur");
    await flushPromises();

    const [patch] = await requestsTo("PATCH", `/api/v1/transactions/${tx.id}/`);
    expect(patch?.body).toEqual({ description: "Coffee beans" });
  });

  // GIVEN: a posted transaction
  // WHEN:  the user attaches a photo and the upload fails
  // THEN:  an error message says the photo was not attached
  //
  it("reports a failed attachment upload", async () => {
    const tx = makeTransaction({ bank_account: account.id });
    serveTransactions([tx]);
    server.use(
      http.patch(`/api/v1/transactions/${tx.id}/`, () =>
        HttpResponse.json({ image: ["File too large."] }, { status: 400 }),
      ),
    );
    // The view opens the browser's file picker with a detached
    // `<input type="file">`; answer it with a chosen file.
    //
    vi.spyOn(HTMLInputElement.prototype, "click").mockImplementation(
      function (this: HTMLInputElement) {
        Object.defineProperty(this, "files", { value: [new File(["x"], "receipt.png")] });
        this.onchange?.(new Event("change"));
      },
    );
    const { wrapper } = await openApp(`/transactions/${tx.id}/`);

    const attach = wrapper.findAll("button").find((b) => b.text() === "Attach photo")!;
    await attach.trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("File too large.");
    expect(wrapper.text()).toMatch(/Couldn't attach the photo/);
  });

  // GIVEN: a transaction with no budget allocations
  // WHEN:  the user assigns it to a budget in the split editor
  // THEN:  the splits are posted and the new allocation is shown
  //  AND:  the account's budgets are refetched for current balances
  //
  it("assigns the transaction to a budget", async () => {
    const tx = makeTransaction({ bank_account: account.id, amount: "-20.00" });
    const rent = makeBudget({ name: "Rent", bank_account: account.id, budget_type: "R" });
    serveTransactions([tx]);
    server.use(
      http.get("/api/v1/budgets/", () => HttpResponse.json(makePage([rent]))),
      http.post(`/api/v1/transactions/${tx.id}/splits/`, () =>
        HttpResponse.json([
          makeAllocation({ transaction: tx.id, budget: rent.id, amount: "-20.00" }),
        ]),
      ),
    );
    const { wrapper } = await openApp(`/transactions/${tx.id}/`);

    await wrapper
      .findAll("button")
      .find((b) => b.text().includes("Assign to budget"))!
      .trigger("click");
    const select = document.body.querySelector<HTMLSelectElement>(".split-row-select")!;
    select.value = rent.id;
    select.dispatchEvent(new Event("change"));
    await flushPromises();
    const save = Array.from(document.body.querySelectorAll("button")).find(
      (b) => b.textContent?.trim() === "Save",
    )!;
    save.click();
    await flushPromises();

    const [post] = await requestsTo("POST", `/api/v1/transactions/${tx.id}/splits/`);
    expect(post.body).toEqual({ splits: { [rent.id]: "20.00" } });
    expect(wrapper.text()).toContain("Rent");
    expect(wrapper.text()).toContain("Fully allocated");
    expect((await requestsTo("GET", "/api/v1/budgets/")).length).toBeGreaterThanOrEqual(2);
  });

  // GIVEN: the transaction list's order saved in the nav store
  // WHEN:  the middle transaction is open and the user steps next
  // THEN:  the next transaction opens
  //
  it("steps to the next transaction", async () => {
    const txs = [0, 1, 2].map(() => makeTransaction({ bank_account: account.id }));
    serveTransactions(txs);
    useTransactionNavStore().setIds(txs.map((t) => t.id));
    const { wrapper, router } = await openApp(`/transactions/${txs[1].id}/`);

    await wrapper.get('button[aria-label="Next transaction"]').trigger("click");

    await vi.waitFor(() =>
      expect(router.currentRoute.value.path).toBe(`/transactions/${txs[2].id}/`),
    );
    expect(wrapper.find('button[aria-label="Previous transaction"]').exists()).toBe(true);
  });
});
