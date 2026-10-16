//
// `usePageReturn` tests: how long the page was hidden when it is shown
// again, the network coming back, and removing the listeners.
//

// 3rd party imports
//
import { afterEach, describe, expect, it, vi } from "vitest";

// app imports
//
import { usePageReturn } from "@/composables/usePageReturn";
import { setPageVisibility, withSetup } from "../helpers";

////////////////////////////////////////////////////////////////////////
//
describe("usePageReturn", () => {
  afterEach(() => vi.useRealTimers());

  // GIVEN: a page that is hidden for a while
  // WHEN:  it is shown again
  // THEN:  `shown` receives how long it was hidden, once
  //
  it("reports how long the page was hidden", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-07T12:00:00Z"));
    const shown = vi.fn();
    withSetup(() => usePageReturn({ shown }));

    setPageVisibility("hidden");
    vi.setSystemTime(new Date("2026-10-07T12:01:30Z"));
    setPageVisibility("visible");
    setPageVisibility("visible");

    expect(shown.mock.calls).toEqual([[90_000]]);
  });

  // GIVEN: the network went away
  // WHEN:  it comes back
  // THEN:  `online` is called
  //
  it("reports the network coming back", () => {
    const online = vi.fn();
    withSetup(() => usePageReturn({ online }));

    window.dispatchEvent(new Event("online"));

    expect(online).toHaveBeenCalledOnce();
  });

  // GIVEN: a component using it
  // WHEN:  the component unmounts
  // THEN:  later visibility and network changes are not reported
  //
  it("stops with its component", () => {
    const shown = vi.fn();
    const online = vi.fn();
    const { wrapper } = withSetup(() => usePageReturn({ shown, online }));

    wrapper.unmount();
    setPageVisibility("hidden");
    setPageVisibility("visible");
    window.dispatchEvent(new Event("online"));

    expect([shown.mock.calls, online.mock.calls]).toEqual([[], []]);
  });
});
