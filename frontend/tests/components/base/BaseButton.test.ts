//
// BaseButton and BaseIconButton tests: each variant renders its token
// classes, and attributes, listeners and states reach the element.
//

// 3rd party imports
//
import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

// app imports
//
import BaseButton from "@/components/base/BaseButton.vue";
import type { ButtonVariant } from "@/components/base/BaseButton.vue";
import BaseIconButton from "@/components/base/BaseIconButton.vue";

////////////////////////////////////////////////////////////////////////
//
describe("BaseButton", () => {
  // GIVEN: a variant
  // WHEN:  the button renders
  // THEN:  it carries that variant's colour tokens and its hover only
  //        applies while enabled
  //
  it.each<[ButtonVariant, string[]]>([
    [
      "primary",
      ["bg-accent", "text-fg-on-accent", "enabled:hover:bg-accent-hover"],
    ],
    [
      "secondary",
      ["border-border", "text-fg", "enabled:hover:bg-surface-sunken"],
    ],
    ["danger", ["bg-danger-solid", "enabled:hover:bg-danger-solid-hover"]],
    ["danger-secondary", ["border-danger-solid", "text-danger-fg"]],
    ["ghost", ["text-accent-fg", "enabled:hover:bg-accent-subtle"]],
    ["link", ["text-fg-link", "enabled:hover:text-accent-hover"]],
    ["link-danger", ["text-danger-fg"]],
  ])("renders the %s variant", (variant, expected) => {
    const classes = mount(BaseButton, { props: { variant } }).classes();
    for (const cls of expected) expect(classes).toContain(cls);
  });

  // GIVEN: a filled button in each size, and a link-style button
  // WHEN:  they render
  // THEN:  filled buttons share one shape and pad by size; link-style
  //        buttons have no padding
  //
  it.each<[{ variant?: ButtonVariant; size: "sm" | "md" }, string[]]>([
    [{ size: "md" }, ["rounded-control", "px-4", "py-2.5", "tap-target"]],
    [{ size: "sm" }, ["rounded-control", "px-3", "py-2"]],
    [{ variant: "link", size: "sm" }, ["text-meta", "font-medium"]],
  ])("sizes %o", (props, expected) => {
    const classes = mount(BaseButton, { props }).classes();
    for (const cls of expected) expect(classes).toContain(cls);
    if (props.variant === "link") expect(classes).not.toContain("px-3");
  });

  // GIVEN: a filled and an outlined variant
  // WHEN:  they render
  // THEN:  the filled one turns grey when disabled; the outlined one
  //        fades
  //
  it.each<[ButtonVariant, string[]]>([
    ["primary", ["disabled:bg-surface-strong", "disabled:text-fg-disabled"]],
    ["danger", ["disabled:bg-surface-strong"]],
    ["secondary", ["disabled:opacity-50"]],
  ])("styles a disabled %s button", (variant, expected) => {
    const classes = mount(BaseButton, { props: { variant } }).classes();
    for (const cls of expected) expect(classes).toContain(cls);
  });

  // GIVEN: attributes, a listener and the `loading` state
  // WHEN:  the button renders and is clicked
  // THEN:  the attributes land on the `<button>`, it is a non-submitting
  //        `type="button"`, it is disabled and busy while loading, and
  //        an enabled click reaches the listener
  //
  it("forwards attributes, listeners and states", async () => {
    const onClick = vi.fn();
    const wrapper = mount(BaseButton, {
      props: { loading: true },
      attrs: { "data-x": "1", onClick },
      slots: { default: "Save" },
    });
    expect(wrapper.element.tagName).toBe("BUTTON");
    expect(wrapper.attributes()).toMatchObject({
      "data-x": "1",
      type: "button",
      "aria-busy": "true",
    });
    expect(wrapper.attributes("disabled")).toBeDefined();
    expect(wrapper.text()).toBe("Save");

    await wrapper.setProps({ loading: false });
    await wrapper.trigger("click");
    expect(onClick).toHaveBeenCalledOnce();
  });

  // GIVEN: `as="a"` with an href
  // WHEN:  it renders
  // THEN:  it is a link with the button styles, plain `hover:` classes
  //        and no button-only attributes
  //
  it("renders as a link", () => {
    const wrapper = mount(BaseButton, {
      props: { as: "a" },
      attrs: { href: "/x/" },
    });
    expect(wrapper.element.tagName).toBe("A");
    expect(wrapper.attributes("href")).toBe("/x/");
    expect(wrapper.attributes("type")).toBeUndefined();
    expect(wrapper.classes()).toContain("hover:bg-accent-hover");
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("BaseIconButton", () => {
  // GIVEN: a size, tone or pressed state
  // WHEN:  the icon button renders
  // THEN:  it has the matching dimensions and colours, and the label is
  //        its accessible name
  //
  type IconProps = {
    size?: "sm" | "md";
    tone?: "default" | "danger";
    pressed?: boolean;
  };
  it.each<[IconProps, string[]]>([
    [{ size: "md" }, ["h-10", "w-10", "text-fg-muted"]],
    [{ size: "sm" }, ["h-7", "w-7", "tap-target"]],
    [{ tone: "danger" }, ["hover:bg-danger-bg", "hover:text-danger-fg"]],
    [{ pressed: true }, ["bg-accent", "text-fg-on-accent"]],
  ])("renders %o", (props, expected) => {
    const wrapper = mount(BaseIconButton, {
      props: { label: "Search", ...props },
    });
    expect(wrapper.attributes("aria-label")).toBe("Search");
    for (const cls of expected) expect(wrapper.classes()).toContain(cls);
  });

  // GIVEN: `pressed` given, and not given
  // WHEN:  the icon button renders
  // THEN:  only the toggle form carries `aria-pressed`
  //
  it("sets aria-pressed only for a toggle", () => {
    expect(
      mount(BaseIconButton, { props: { label: "x" } }).attributes(
        "aria-pressed",
      ),
    ).toBeUndefined();
    expect(
      mount(BaseIconButton, {
        props: { label: "x", pressed: false },
      }).attributes("aria-pressed"),
    ).toBe("false");
  });
});
