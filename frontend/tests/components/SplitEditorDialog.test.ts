//
// SplitEditorDialog tests: the over-allocation check agrees with the
// amounts the dialog emits.
//

// 3rd party imports
//
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

// app imports
//
import SplitEditorDialog from "@/components/transactions/SplitEditorDialog.vue";
import { Money } from "@/domain/money";
import { budgetFromDto } from "@/models/budget";
import { makeBudget } from "../mocks/factories";

////////////////////////////////////////////////////////////////////////
//
describe("SplitEditorDialog", () => {
  // GIVEN: a $10.00 transaction split $5.005 / $4.995, which sums to
  //        exactly $10.00 but is sent rounded to cents as $5.01 / $5.00
  // WHEN:  the dialog opens
  // THEN:  it reports the split as over by $0.01 and Save is disabled,
  //        so a split larger than the transaction is never emitted
  //
  it("checks the rounded amounts it would send", async () => {
    const [a, b] = [
      budgetFromDto(makeBudget({ name: "Groceries" })),
      budgetFromDto(makeBudget({ name: "Dining" })),
    ];
    const wrapper = mount(SplitEditorDialog, {
      props: {
        open: false,
        budgets: [a, b],
        transactionAmount: Money.of("-10.00"),
        initialSplits: [
          { budgetId: a.id, amount: "5.005" },
          { budgetId: b.id, amount: "4.995" },
        ],
      },
      global: { stubs: { teleport: true } },
    });
    await wrapper.setProps({ open: true });

    const save = wrapper
      .findAll("button")
      .find((btn) => btn.text() === "Save")!;
    expect(wrapper.text()).toContain("Over by");
    expect(wrapper.text()).toContain("$0.01");
    expect(save.attributes("disabled")).toBeDefined();
    await save.trigger("click");
    expect(wrapper.emitted("save")).toBeUndefined();
  });
});
