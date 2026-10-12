//
// Invalidation store tests: which subscribers a signal reaches,
// coalescing, holding signals while the page is hidden, the
// shown-again threshold, and subscriptions ending with their
// component.
//

// 3rd party imports
//
import { flushPromises } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

// app imports
//
import type { ChangeScope, Interest } from "@/stores/invalidation";
import { STALE_AFTER_MS, useInvalidationStore } from "@/stores/invalidation";
import { setPageVisibility, withSetup } from "../helpers";

////////////////////////////////////////////////////////////////////////
//
const ACCOUNT_A = "acct-a";
const ACCOUNT_B = "acct-b";

////////////////////////////////////////////////////////////////////////
//
describe("invalidation store", () => {
  // GIVEN: a subscriber showing budgets for bank account A
  // WHEN:  a change is signalled
  // THEN:  it refreshes when the scope names its account (or none) and
  //        one of its kinds (or none)
  //
  it.each<[string, ChangeScope, boolean]>([
    ["everything", {}, true],
    ["its account", { bankAccountId: ACCOUNT_A }, true],
    ["another account", { bankAccountId: ACCOUNT_B }, false],
    ["its kind", { kinds: ["budgets"] }, true],
    ["another kind", { kinds: ["transactions"] }, false],
    [
      "its account and kind",
      { bankAccountId: ACCOUNT_A, kinds: ["transactions", "budgets"] },
      true,
    ],
  ])("a signal for %s", async (_name, scope, refreshed) => {
    const store = useInvalidationStore();
    const refresh = vi.fn();
    store.onInvalidate(
      () => ({ bankAccountId: ACCOUNT_A, kinds: ["budgets"] }),
      refresh,
    );

    await store.invalidate(scope);

    expect(refresh).toHaveBeenCalledTimes(refreshed ? 1 : 0);
  });

  // GIVEN: subscribers for every bank account, and for none right now
  // WHEN:  a change to one bank account is signalled
  // THEN:  the every-account subscriber refreshes; the other does not
  //
  it.each<[string, Interest | null, number]>([
    ["every bank account", { kinds: ["bankAccounts"] }, 1],
    ["nothing shown", null, 0],
  ])("a subscriber showing %s", async (_name, interest, calls) => {
    const store = useInvalidationStore();
    const refresh = vi.fn();
    store.onInvalidate(() => interest, refresh);

    await store.invalidate({ bankAccountId: ACCOUNT_A });

    expect(refresh).toHaveBeenCalledTimes(calls);
  });

  // GIVEN: a subscriber
  // WHEN:  several changes are signalled in the same tick
  // THEN:  it refreshes once, and every signal resolves after it
  //
  it("coalesces signals raised together", async () => {
    const store = useInvalidationStore();
    let finish!: () => void;
    const refresh = vi.fn(
      () => new Promise<void>((resolve) => (finish = resolve)),
    );
    store.onInvalidate(() => ({ kinds: ["budgets"] }), refresh);

    let settled = 0;
    void store.invalidate({ kinds: ["budgets"] }).then(() => settled++);
    void store.invalidate({}).then(() => settled++);
    await flushPromises();
    expect.soft(settled, "waits for the refresh").toBe(0);
    finish();
    await flushPromises();

    expect.soft(refresh, "one refresh").toHaveBeenCalledOnce();
    expect.soft(settled, "both resolve").toBe(2);
  });

  // GIVEN: a hidden page
  // WHEN:  a change is signalled, and the page is shown again soon
  // THEN:  nothing refreshes while hidden; the held signal is flushed
  //        when shown
  //
  it("holds signals while the page is hidden", async () => {
    const store = useInvalidationStore();
    const refresh = vi.fn();
    store.onInvalidate(() => ({ kinds: ["transactions"] }), refresh);
    setPageVisibility("hidden");

    const signal = store.invalidate({ kinds: ["transactions"] });
    await flushPromises();
    expect(refresh).not.toHaveBeenCalled();

    setPageVisibility("visible");
    await store.pageShown(1_000);
    await signal;

    expect(refresh).toHaveBeenCalledOnce();
  });

  // GIVEN: a page shown again with nothing signalled meanwhile
  // WHEN:  it was hidden for some time
  // THEN:  everything refreshes only when hidden at least
  //        `STALE_AFTER_MS`
  //
  it.each([
    [STALE_AFTER_MS - 1, 0],
    [STALE_AFTER_MS, 1],
  ])("shown again after %i ms hidden", async (hiddenMs, calls) => {
    const store = useInvalidationStore();
    const refresh = vi.fn();
    store.onInvalidate(() => ({ kinds: ["budgets"] }), refresh);

    await store.pageShown(hiddenMs);

    expect(refresh).toHaveBeenCalledTimes(calls);
  });

  // GIVEN: a subscription made by a component
  // WHEN:  the component unmounts
  // THEN:  later signals do not reach it
  //
  it("ends a subscription with its component", async () => {
    const store = useInvalidationStore();
    const refresh = vi.fn();
    const { wrapper } = withSetup(() =>
      store.onInvalidate(() => ({ kinds: ["budgets"] }), refresh),
    );

    wrapper.unmount();
    await store.invalidate();

    expect(refresh).not.toHaveBeenCalled();
  });

  // GIVEN: a signal held while the page is hidden
  // WHEN:  the user signs out (stores reset), and the page is shown
  // THEN:  the held signal is dropped and its caller released
  //
  it("drops held signals on reset", async () => {
    const store = useInvalidationStore();
    const refresh = vi.fn();
    store.onInvalidate(() => ({ kinds: ["budgets"] }), refresh);
    setPageVisibility("hidden");
    const signal = store.invalidate();

    store.reset();
    await signal;
    setPageVisibility("visible");
    await store.pageShown(0);

    expect(refresh).not.toHaveBeenCalled();
  });
});
