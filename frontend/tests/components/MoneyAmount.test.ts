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
  // GIVEN: an amount as an API decimal string plus currency, or as Money
  // WHEN:  it renders
  // THEN:  both forms show the same currency text and aria-label
  //
  it.each([[{ amount: "-12.3", currency: "USD" }], [{ amount: Money.of("-12.3", "USD") }]])(
    "formats %j",
    (props) => {
      const wrapper = mount(MoneyAmount, { props });
      expect(wrapper.text()).toBe("-$12.30");
      expect(wrapper.attributes("aria-label")).toBe("-12.30 USD");
    },
  );

  // GIVEN: `coloured` and a negative, positive or zero amount
  // WHEN:  it renders
  // THEN:  negatives are coral, positives mint, zero uncoloured
  //
  it.each([
    ["-1", "text-coral-600"],
    ["1", "text-mint-600"],
    ["0", null],
  ])("colours %s", (amount, cls) => {
    const wrapper = mount(MoneyAmount, { props: { amount, currency: "USD", coloured: true } });
    const classes = wrapper.classes();
    expect(classes.includes("text-coral-600")).toBe(cls === "text-coral-600");
    expect(classes.includes("text-mint-600")).toBe(cls === "text-mint-600");
  });

  // GIVEN: `showSign`
  // WHEN:  a positive amount renders
  // THEN:  it carries a leading plus
  //
  it("shows the sign when asked", () => {
    const wrapper = mount(MoneyAmount, { props: { amount: "5", currency: "USD", showSign: true } });
    expect(wrapper.text()).toBe("+$5.00");
  });
});
