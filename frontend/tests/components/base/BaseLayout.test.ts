//
// BaseCard, BaseCardSection, BaseListRow, BaseSectionHeader,
// BasePageHeader, BaseBanner, BaseBadge and BaseSkeleton tests: each
// renders its token classes and passes attributes through.
//

// 3rd party imports
//
import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

// app imports
//
import BaseBadge from "@/components/base/BaseBadge.vue";
import BaseBanner from "@/components/base/BaseBanner.vue";
import type { BannerTone } from "@/components/base/BaseBanner.vue";
import BaseCard from "@/components/base/BaseCard.vue";
import BaseCardSection from "@/components/base/BaseCardSection.vue";
import BaseListRow from "@/components/base/BaseListRow.vue";
import BasePageHeader from "@/components/base/BasePageHeader.vue";
import BaseSectionHeader from "@/components/base/BaseSectionHeader.vue";
import BaseSkeleton from "@/components/base/BaseSkeleton.vue";

////////////////////////////////////////////////////////////////////////
//
describe("BaseCard / BaseCardSection", () => {
  // GIVEN: a card, padded or not, rendered as another element
  // WHEN:  it renders
  // THEN:  it has the card outline, the card padding only when padded,
  //        the requested element, and the caller's attributes
  //
  it.each([
    [false, "div", false],
    [true, "section", true],
  ])("padded=%s as=%s", (padded, as, hasPad) => {
    const wrapper = mount(BaseCard, {
      props: { padded, as },
      attrs: { "data-x": "1" },
    });
    expect(wrapper.element.tagName).toBe(as.toUpperCase());
    expect(wrapper.classes()).toEqual(
      expect.arrayContaining(["rounded-card", "border-border", "bg-surface"]),
    );
    expect(wrapper.classes().includes("px-card-x")).toBe(hasPad);
    expect(wrapper.attributes("data-x")).toBe("1");
  });

  // GIVEN: a card section
  // WHEN:  it renders
  // THEN:  it pads with the card tokens and divides from the one above
  //
  it("pads and divides a section", () => {
    expect(mount(BaseCardSection).classes()).toEqual(
      expect.arrayContaining([
        "px-card-x",
        "py-card-y",
        "border-border-subtle",
      ]),
    );
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("BaseListRow", () => {
  // GIVEN: a row rendered as a button with a chevron, and a plain row
  // WHEN:  they render and the button is clicked
  // THEN:  the button row has a hover tint, a trailing chevron and
  //        forwards its click; the plain row has neither; `align`
  //        top-aligns a row
  //
  it("renders interactive and static rows", async () => {
    const onClick = vi.fn();
    const row = mount(BaseListRow, {
      props: { as: "button", chevron: true },
      attrs: { onClick },
      slots: { default: "Default account" },
    });
    expect(row.element.tagName).toBe("BUTTON");
    expect(row.attributes("type")).toBe("button");
    expect(row.classes()).toContain("hover:bg-surface-sunken");
    expect(row.find("svg").exists()).toBe(true);
    await row.trigger("click");
    expect(onClick).toHaveBeenCalledOnce();

    const plain = mount(BaseListRow, { slots: { default: "x" } });
    expect(plain.classes()).not.toContain("hover:bg-surface-sunken");
    expect(plain.classes()).toContain("items-center");
    expect(plain.find("svg").exists()).toBe(false);

    const top = mount(BaseListRow, { props: { align: "start" } });
    expect(top.classes()).toContain("items-start");
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("BaseSectionHeader / BasePageHeader", () => {
  // GIVEN: a section header and a page header with actions
  // WHEN:  they render
  // THEN:  the section title is an overline h2, the page title the
  //        page's h1, and both show their actions
  //
  it("renders the headings and actions", () => {
    const section = mount(BaseSectionHeader, {
      props: { title: "Budgets" },
      slots: { actions: "<a>See all</a>" },
    });
    expect(section.get("h2").classes()).toEqual(
      expect.arrayContaining(["text-overline", "uppercase", "text-fg-muted"]),
    );
    expect(section.text()).toContain("See all");

    const page = mount(BasePageHeader, {
      props: { title: "Profile" },
      slots: { actions: "<button>Edit</button>" },
    });
    expect(page.get("h1").text()).toBe("Profile");
    expect(page.get("h1").classes()).toContain("text-page-title");
    expect(page.text()).toContain("Edit");
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("BaseBanner", () => {
  // GIVEN: a banner tone
  // WHEN:  it renders
  // THEN:  it uses that status's background, text and border, and only
  //        a danger banner is an alert
  //
  it.each<[BannerTone, string]>([
    ["danger", "alert"],
    ["success", "status"],
    ["info", "status"],
    ["warning", "status"],
  ])("renders the %s tone", (tone, role) => {
    const wrapper = mount(BaseBanner, {
      props: { tone },
      slots: { default: "Message" },
    });
    expect(wrapper.attributes("role")).toBe(role);
    expect(wrapper.classes()).toEqual(
      expect.arrayContaining([
        `bg-${tone}-bg`,
        `text-${tone}-fg`,
        `border-${tone}-border`,
      ]),
    );
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("BaseBadge / BaseSkeleton", () => {
  // GIVEN: a badge tone and variant
  // WHEN:  it renders
  // THEN:  it uses the badge role with the tone's ring or tint
  //
  type BadgeProps = {
    tone: "warning" | "neutral";
    variant?: "outline" | "soft";
  };
  it.each<[BadgeProps, string[]]>([
    [{ tone: "warning" }, ["ring-warning-border", "text-warning-fg"]],
    [{ tone: "neutral" }, ["ring-border-emphasis", "text-fg-muted"]],
    [{ tone: "warning", variant: "soft" }, ["bg-warning-bg", "rounded-pill"]],
  ])("renders %o", (props, expected) => {
    const classes = mount(BaseBadge, { props }).classes();
    expect(classes).toEqual(
      expect.arrayContaining(["text-badge", ...expected]),
    );
  });

  // GIVEN: a card skeleton and a line skeleton
  // WHEN:  they render
  // THEN:  both pulse, are hidden from screen readers, and take the
  //        radius of their shape
  //
  it.each([
    ["card", "rounded-card"],
    ["line", "rounded-xs"],
  ] as const)("renders a %s skeleton", (shape, radius) => {
    const wrapper = mount(BaseSkeleton, { props: { shape } });
    expect(wrapper.attributes("aria-hidden")).toBe("true");
    expect(wrapper.classes()).toEqual(
      expect.arrayContaining(["animate-pulse", "bg-surface-muted", radius]),
    );
  });
});
