//
// `useRefreshOnReturn` tests: the page shown again after a long or a
// short time hidden, end to end from the visibility event to the
// requests a mounted page sends.
//

// 3rd party imports
//
import { flushPromises } from "@vue/test-utils";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

// app imports
//
import { useRefreshOnReturn } from "@/features/shell/useRefreshOnReturn";
import { STALE_AFTER_MS } from "@/stores/invalidation";
import BudgetsView from "@/views/BudgetsView.vue";
import {
  mountWithApp,
  setPageVisibility,
  withAccounts,
  withAuth,
  withSetup,
} from "../../helpers";
import { makeBankAccount, makeBudget, makePage } from "../../mocks/factories";
import { requestsTo, server } from "../../mocks/server";

////////////////////////////////////////////////////////////////////////
//
describe("useRefreshOnReturn", () => {
  afterEach(() => vi.useRealTimers());

  // GIVEN: the budgets page open
  // WHEN:  the user switches away and back after some time
  // THEN:  the page refetches its budgets only when it was away at
  //        least `STALE_AFTER_MS`
  //
  it.each([
    ["a quick switch", STALE_AFTER_MS - 1_000, 0],
    ["a long absence", STALE_AFTER_MS, 1],
  ])("after %s", async (_name, awayMs, refetches) => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-07T12:00:00Z"));
    withAuth();
    const account = makeBankAccount();
    withAccounts([account]);
    server.use(
      http.get("/api/v1/bank-accounts/", () =>
        HttpResponse.json(makePage([account])),
      ),
      http.get("/api/v1/budgets/", () =>
        HttpResponse.json(makePage([makeBudget({ bank_account: account.id })])),
      ),
    );
    withSetup(() => useRefreshOnReturn());
    await mountWithApp(BudgetsView, { route: "/budgets/" });
    const before = (await requestsTo("GET", "/api/v1/budgets/")).length;

    setPageVisibility("hidden");
    vi.setSystemTime(new Date(Date.now() + awayMs));
    setPageVisibility("visible");
    await flushPromises();

    expect((await requestsTo("GET", "/api/v1/budgets/")).length).toBe(
      before + refetches,
    );
  });
});
