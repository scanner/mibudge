//
// `usePullToRefresh` tests: a pull from the top past the trigger
// refreshes; a short pull, a pull from further down, and a cancelled
// touch do not.
//

// 3rd party imports
//
import { flushPromises } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

// app imports
//
import { TRIGGER_PX, usePullToRefresh } from "@/composables/usePullToRefresh";
import { withSetup } from "../helpers";

////////////////////////////////////////////////////////////////////////
//
function touch(type: string, y: number, target: EventTarget = window): void {
  const event = new Event(type, { bubbles: true }) as Event & {
    touches: { clientY: number }[];
  };
  event.touches =
    type === "touchend" || type === "touchcancel" ? [] : [{ clientY: y }];
  target.dispatchEvent(event);
}

// Pull down by `dy` px of finger travel and release (or cancel).
//
function pull(
  dy: number,
  release = "touchend",
  target: EventTarget = window,
): void {
  touch("touchstart", 100, target);
  touch("touchmove", 100 + dy, target);
  touch(release, 100 + dy, target);
}

// An element inside an open sheet, attached to the document.
//
function inSheet(): Element {
  const dialog = document.createElement("div");
  dialog.setAttribute("role", "dialog");
  const inner = document.createElement("div");
  dialog.append(inner);
  document.body.append(dialog);
  return inner;
}

////////////////////////////////////////////////////////////////////////
//
describe("usePullToRefresh", () => {
  // GIVEN: the page scrolled to the top
  // WHEN:  the user pulls down by some distance and releases
  // THEN:  it refreshes only past the trigger, and not when cancelled
  //        or when the pull is inside an open sheet
  //
  it.each([
    ["past the trigger", TRIGGER_PX * 2 + 10, "touchend", false, 1],
    ["short of the trigger", TRIGGER_PX, "touchend", false, 0],
    ["and is cancelled", TRIGGER_PX * 2 + 10, "touchcancel", false, 0],
    ["inside a sheet", TRIGGER_PX * 2 + 10, "touchend", true, 0],
  ])("a pull %s", async (_name, dy, release, sheet, calls) => {
    const onRefresh = vi.fn(async () => undefined);
    withSetup(() => usePullToRefresh(onRefresh));

    pull(dy, release, sheet ? inSheet() : window);
    await flushPromises();

    expect(onRefresh).toHaveBeenCalledTimes(calls);
  });

  // GIVEN: the page scrolled down
  // WHEN:  the user drags down
  // THEN:  it scrolls the page and does not refresh
  //
  it("ignores a pull that does not start at the top", async () => {
    vi.spyOn(window, "scrollY", "get").mockReturnValue(300);
    if (document.scrollingElement)
      vi.spyOn(document.scrollingElement, "scrollTop", "get").mockReturnValue(
        300,
      );
    const onRefresh = vi.fn(async () => undefined);
    const { result } = withSetup(() => usePullToRefresh(onRefresh));

    touch("touchstart", 100);
    touch("touchmove", 400);
    expect(result.distance.value).toBe(0);
    touch("touchend", 400);
    await flushPromises();

    expect(onRefresh).not.toHaveBeenCalled();
  });

  // GIVEN: a refresh started by a pull
  // WHEN:  it is running, and once it settles
  // THEN:  `refreshing` is true, then false; a second pull meanwhile
  //        starts nothing
  //
  it("tracks a running refresh", async () => {
    let finish!: () => void;
    const onRefresh = vi.fn(
      () => new Promise<void>((resolve) => (finish = resolve)),
    );
    const { result } = withSetup(() => usePullToRefresh(onRefresh));

    pull(TRIGGER_PX * 3);
    expect(result.refreshing.value).toBe(true);
    pull(TRIGGER_PX * 3);
    finish();
    await flushPromises();

    expect.soft(result.refreshing.value, "done").toBe(false);
    expect.soft(onRefresh, "one refresh").toHaveBeenCalledOnce();
  });
});
