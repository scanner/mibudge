//
// `useModal` tests: the shared scroll lock, Escape for the topmost
// modal only, focus return, and cleanup on unmount.
//

// 3rd party imports
//
import { afterEach, describe, expect, it, vi } from "vitest";
import { nextTick, ref } from "vue";

// app imports
//
import { isModalOpen, useModal } from "@/composables/useModal";
import { withSetup } from "../helpers";

////////////////////////////////////////////////////////////////////////
//
function escape(): void {
  window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
}

afterEach(() => {
  document.body.style.overflow = "";
});

////////////////////////////////////////////////////////////////////////
//
describe("useModal", () => {
  // GIVEN: two open modals, one stacked on the other
  // WHEN:  the top one closes, then the bottom one
  // THEN:  the page stays locked until the last one closes
  //
  it("shares one scroll lock between stacked modals", async () => {
    const [a, b] = [ref(false), ref(false)];
    withSetup(() => useModal(() => a.value, vi.fn()));
    withSetup(() => useModal(() => b.value, vi.fn()));

    a.value = true;
    await nextTick();
    b.value = true;
    await nextTick();
    expect(document.body.style.overflow).toBe("hidden");

    b.value = false;
    await nextTick();
    expect(document.body.style.overflow).toBe("hidden");

    a.value = false;
    await nextTick();
    expect(document.body.style.overflow).toBe("");
    expect(isModalOpen()).toBe(false);
  });

  // GIVEN: two open modals
  // WHEN:  Escape is pressed
  // THEN:  only the topmost modal is asked to close
  //
  it("closes only the topmost modal on Escape", async () => {
    const [closeA, closeB] = [vi.fn(), vi.fn()];
    const a = withSetup(() => useModal(() => true, closeA));
    const b = withSetup(() => useModal(() => true, closeB));
    await nextTick();

    expect(b.result.isTopmost.value).toBe(true);
    expect(a.result.isTopmost.value).toBe(false);
    escape();
    expect(closeB).toHaveBeenCalledOnce();
    expect(closeA).not.toHaveBeenCalled();
  });

  // GIVEN: an open modal
  // WHEN:  its component unmounts without closing
  // THEN:  the scroll lock is released and Escape no longer reaches it
  //
  it("releases the lock when unmounted while open", async () => {
    const close = vi.fn();
    const { wrapper } = withSetup(() => useModal(() => true, close));
    await nextTick();
    expect(document.body.style.overflow).toBe("hidden");

    wrapper.unmount();

    expect(document.body.style.overflow).toBe("");
    escape();
    expect(close).not.toHaveBeenCalled();
  });

  // GIVEN: a button with focus
  // WHEN:  a modal opens and then closes
  // THEN:  focus returns to the button
  //
  it("returns focus on close", async () => {
    const button = document.createElement("button");
    document.body.appendChild(button);
    button.focus();
    const open = ref(false);
    withSetup(() => useModal(() => open.value, vi.fn()));

    open.value = true;
    await nextTick();
    (document.activeElement as HTMLElement | null)?.blur();
    open.value = false;
    await nextTick();

    expect(document.activeElement).toBe(button);
    button.remove();
  });

  // GIVEN: a modal that does not lock scrolling
  // WHEN:  it opens
  // THEN:  the page stays scrollable
  //
  it("can skip the scroll lock", async () => {
    withSetup(() => useModal(() => true, vi.fn(), { lockScroll: false }));
    await nextTick();
    expect(document.body.style.overflow).toBe("");
  });
});
