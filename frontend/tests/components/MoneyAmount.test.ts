//
// MoneyAmount tests: formatting, sign colouring and the screen-reader
// label.
//

// 3rd party imports
//
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

// app imports
//
import MoneyAmount from "@/components/shared/MoneyAmount.vue";
import { Money } from "@/domain/money";

////////////////////////////////////////////////////////////////////////
//
describe("MoneyAmount", () => {
  // GIVEN: an amount
  // WHEN:  it renders
  // THEN:  it shows the currency text, with the raw decimal as the
  //        aria-label
  //
  it("formats the amount", () => {
    const wrapper = mount(MoneyAmount, {
      props: { amount: Money.of("-12.3", "USD") },
    });
    expect(wrapper.text()).toBe("-$12.30");
    expect(wrapper.attributes("aria-label")).toBe("-12.30 USD");
  });

  // GIVEN: `coloured` and a negative, positive or zero amount
  // WHEN:  it renders
  // THEN:  negatives are coral, positives mint, zero uncoloured
  //
  it.each([
    ["-1", "text-coral-600"],
    ["1", "text-mint-600"],
    ["0", null],
  ])("colours %s", (amount, cls) => {
    const wrapper = mount(MoneyAmount, {
      props: { amount: Money.of(amount), coloured: true },
    });
    const classes = wrapper.classes();
    expect(classes.includes("text-coral-600")).toBe(cls === "text-coral-600");
    expect(classes.includes("text-mint-600")).toBe(cls === "text-mint-600");
  });

  // GIVEN: `showSign`
  // WHEN:  a positive amount renders
  // THEN:  it carries a leading plus
  //
  it("shows the sign when asked", () => {
    const wrapper = mount(MoneyAmount, {
      props: { amount: Money.of("5"), showSign: true },
    });
    expect(wrapper.text()).toBe("+$5.00");
  });
});
