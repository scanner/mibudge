//
// Stale-chunk recovery: a navigation that fails because a view's chunk
// would not load does one full page load of its target, and never
// reloads for any other error or in a loop.
//

// 3rd party imports
//
import { afterEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import type { Router } from "vue-router";

// app imports
//
import { RELOAD_WINDOW_MS, reloadOnStaleChunk } from "@/router/staleChunk";

////////////////////////////////////////////////////////////////////////
//
// Raise the error the way Vite's preload helper does: dispatch
// `vite:preloadError` with it, then reject the import with it.
//
function viteChunkError(): Error {
  const error = new TypeError("chunk did not load");
  const event = new Event("vite:preloadError", { cancelable: true });
  Object.assign(event, { payload: error });
  window.dispatchEvent(event);
  return error;
}

////////////////////////////////////////////////////////////////////////
//
// A router whose `/budgets/` view fails to load with `makeError()`, and
// the reload spy it reports to.
//
function makeRouter(makeError: () => Error): {
  router: Router;
  reload: ReturnType<typeof vi.fn>;
} {
  const router = createRouter({
    history: createMemoryHistory("/app/"),
    routes: [
      { path: "/", component: { render: () => null } },
      { path: "/budgets/", component: () => Promise.reject(makeError()) },
    ],
  });
  const reload = vi.fn();
  reloadOnStaleChunk(router, reload);
  return { router, reload };
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

////////////////////////////////////////////////////////////////////////
//
describe("reloadOnStaleChunk", () => {
  // GIVEN: an open tab whose next view's chunk no longer exists, as
  //        reported by Vite or by the browser's own message
  // WHEN:  the user navigates to that view
  // THEN:  the page does one full load of the target route
  //
  it.each([
    ["a Vite preload error", viteChunkError],
    [
      "Chrome's message",
      () =>
        new TypeError(
          "Failed to fetch dynamically imported module: /static/assets/BudgetsView-x.js",
        ),
    ],
    [
      "Firefox's message",
      () => new TypeError("error loading dynamically imported module"),
    ],
    [
      "Safari's message",
      () => new TypeError("Importing a module script failed."),
    ],
  ])("reloads the target route for %s", async (_name, makeError) => {
    const { router, reload } = makeRouter(makeError);

    await expect(router.push("/budgets/")).rejects.toBeInstanceOf(TypeError);

    expect(reload.mock.calls).toEqual([["/app/budgets/"]]);
  });

  // GIVEN: a navigation that fails for a reason other than a chunk load
  // WHEN:  the router reports the error
  // THEN:  the page is not reloaded
  //
  it("does not reload for any other error", async () => {
    const { router, reload } = makeRouter(() => new Error("render failed"));

    await expect(router.push("/budgets/")).rejects.toThrow("render failed");

    expect(reload).not.toHaveBeenCalled();
  });

  // GIVEN: a reload to the target that just happened, and its chunk is
  //        still missing
  // WHEN:  the navigation fails again, inside and then after the window
  // THEN:  it is not reloaded inside the window, and is reloaded after
  //
  it("reloads a target at most once per window", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    const { router, reload } = makeRouter(viteChunkError);

    await expect(router.push("/budgets/")).rejects.toBeInstanceOf(TypeError);
    await expect(router.push("/budgets/")).rejects.toBeInstanceOf(TypeError);
    expect(reload).toHaveBeenCalledTimes(1);

    vi.setSystemTime(Date.now() + RELOAD_WINDOW_MS);
    await expect(router.push("/budgets/")).rejects.toBeInstanceOf(TypeError);
    expect(reload).toHaveBeenCalledTimes(2);
  });

  // GIVEN: sessionStorage that cannot be used (a private window, blocked
  //        site data)
  // WHEN:  a chunk fails to load
  // THEN:  the page is not reloaded, since a loop could not be stopped
  //
  it("does not reload without sessionStorage", async () => {
    vi.spyOn(window, "sessionStorage", "get").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    const { router, reload } = makeRouter(viteChunkError);

    await expect(router.push("/budgets/")).rejects.toBeInstanceOf(TypeError);

    expect(reload).not.toHaveBeenCalled();
  });
});
