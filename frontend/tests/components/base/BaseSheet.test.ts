//
// BaseSheet tests: it teleports a labelled dialog to the body, closes
// from the scrim and Escape, and lays out its slots.
//

// 3rd party imports
//
import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

// app imports
//
import BaseSheet from "@/components/base/BaseSheet.vue";

////////////////////////////////////////////////////////////////////////
//
function dialog(): HTMLElement {
  return document.body.querySelector<HTMLElement>('[role="dialog"]')!;
}

////////////////////////////////////////////////////////////////////////
//
describe("BaseSheet", () => {
  // GIVEN: an open sheet with a title, a body, header actions and a
  //        footer
  // WHEN:  it renders
  // THEN:  a modal dialog labelled by the title appears in the body
  //        with every slot, and the footer is divided from the body
  //
  it("renders a labelled dialog with its slots", () => {
    mount(BaseSheet, {
      props: { open: true, title: "Allocations" },
      slots: {
        default: "<p>Rows</p>",
        "header-actions": "<button>Cancel</button>",
        footer: "<button>Save</button>",
      },
      attachTo: document.body,
    });
    const el = dialog();
    expect(el.getAttribute("aria-modal")).toBe("true");
    const heading = document.getElementById(
      el.getAttribute("aria-labelledby")!,
    );
    expect(heading?.textContent?.trim()).toBe("Allocations");
    expect(el.textContent).toContain("Rows");
    expect(el.textContent).toContain("Cancel");
    expect(el.textContent).toContain("Save");
    expect(el.querySelector(".border-t")).not.toBeNull();
  });

  // GIVEN: an open sheet with no title
  // WHEN:  it renders
  // THEN:  the dialog is named by `label`
  //
  it("uses label as the accessible name without a title", () => {
    mount(BaseSheet, {
      props: { open: true, label: "Switch bank account" },
      attachTo: document.body,
    });
    expect(dialog().getAttribute("aria-label")).toBe("Switch bank account");
    expect(dialog().getAttribute("aria-labelledby")).toBeNull();
  });

  // GIVEN: an open sheet
  // WHEN:  the user clicks the scrim, then presses Escape
  // THEN:  each emits `close`
  //
  it("closes from the scrim and from Escape", async () => {
    const wrapper = mount(BaseSheet, {
      props: { open: true, title: "Move money" },
      attachTo: document.body,
    });
    document.body.querySelector<HTMLElement>(".bg-scrim\\/40")!.click();
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(wrapper.emitted("close")).toHaveLength(2);
  });

  // GIVEN: a full-screen sheet and a dialog-layer sheet
  // WHEN:  they render
  // THEN:  the full-screen one covers the canvas, and the dialog one
  //        stacks above sheets
  //
  it.each([
    [{ fullscreen: true }, "bg-canvas"],
    [{ layer: "dialog" }, "z-dialog"],
  ] as const)("renders %o", (props, cls) => {
    mount(BaseSheet, {
      props: { open: true, title: "Edit budget", ...props },
      attachTo: document.body,
    });
    expect(document.body.querySelector(`.${cls}`)).not.toBeNull();
  });

  // GIVEN: an open sheet with two buttons
  // WHEN:  it opens, then Tab and Shift+Tab are pressed at its edges
  // THEN:  focus moves to the first button, Tab from the last wraps to
  //        the first, and Shift+Tab from the first wraps to the last
  //
  it("moves focus in and keeps Tab inside", async () => {
    mount(BaseSheet, {
      props: { open: true, title: "Archive budget?" },
      slots: { default: "<button>Cancel</button><button>Archive</button>" },
      attachTo: document.body,
    });
    await flushPromises();
    const [first, last] = Array.from(dialog().querySelectorAll("button"));
    expect(document.activeElement).toBe(first);

    const tab = (shiftKey: boolean) =>
      window.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "Tab",
          shiftKey,
          cancelable: true,
        }),
      );
    last!.focus();
    tab(false);
    expect(document.activeElement).toBe(first);
    tab(true);
    expect(document.activeElement).toBe(last);
  });

  // GIVEN: a closed sheet
  // WHEN:  it mounts
  // THEN:  nothing renders in the body
  //
  it("renders nothing while closed", () => {
    mount(BaseSheet, {
      props: { open: false, title: "x" },
      attachTo: document.body,
    });
    expect(dialog()).toBeNull();
  });
});
