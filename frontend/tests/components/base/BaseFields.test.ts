//
// BaseInput, BaseSelect, BaseTextarea, BaseFormField and BaseToggle
// tests: attributes and `v-model` reach the native control, the invalid
// state shows, and a form field wires its label, hint and error.
//

// 3rd party imports
//
import { mount } from "@vue/test-utils";
import { defineComponent, h, ref } from "vue";
import { describe, expect, it } from "vitest";

// app imports
//
import BaseFormField from "@/components/base/BaseFormField.vue";
import BaseInput from "@/components/base/BaseInput.vue";
import BaseSelect from "@/components/base/BaseSelect.vue";
import BaseTextarea from "@/components/base/BaseTextarea.vue";
import BaseToggle from "@/components/base/BaseToggle.vue";

////////////////////////////////////////////////////////////////////////
//
describe("BaseInput / BaseSelect / BaseTextarea", () => {
  // GIVEN: each field component with attributes and a model value
  // WHEN:  it renders and the user types
  // THEN:  the attributes land on the native control (not a wrapper),
  //        it shows the model value, and input updates the model
  //
  it.each([
    ["input", BaseInput, "INPUT"],
    ["select", BaseSelect, "SELECT"],
    ["textarea", BaseTextarea, "TEXTAREA"],
  ] as const)("binds %s attributes and v-model", async (_n, Comp, tag) => {
    const wrapper = mount(Comp, {
      props: {
        modelValue: "a",
        "onUpdate:modelValue": (v: unknown) =>
          wrapper.setProps({ modelValue: v as string }),
      },
      attrs: { id: "f", autocomplete: "off", class: "w-28" },
      slots:
        tag === "SELECT"
          ? {
              default:
                '<option value="a">A</option><option value="b">B</option>',
            }
          : {},
    });
    const el = wrapper.element as HTMLInputElement;
    expect(el.tagName).toBe(tag);
    expect(wrapper.attributes()).toMatchObject({
      id: "f",
      autocomplete: "off",
    });
    expect(wrapper.classes()).toEqual(
      expect.arrayContaining(["w-28", "rounded-control", "text-input"]),
    );
    expect(el.value).toBe("a");

    await wrapper.setValue("b");
    expect(wrapper.props("modelValue")).toBe("b");
  });

  // GIVEN: `invalid`, `mono` and the compact size
  // WHEN:  an input renders
  // THEN:  it draws the danger border, marks itself invalid, uses the
  //        mono font and the compact padding
  //
  it("renders invalid, mono and compact states", () => {
    const wrapper = mount(BaseInput, {
      props: { invalid: true, mono: true, size: "sm" },
    });
    expect(wrapper.attributes("aria-invalid")).toBe("true");
    expect(wrapper.classes()).toEqual(
      expect.arrayContaining(["border-danger-solid", "font-mono", "py-1.5"]),
    );
    expect(mount(BaseInput).classes()).toContain("border-border-strong");
  });

  // GIVEN: a field with `inline`, and one without
  // WHEN:  they render
  // THEN:  only the default field fills its container's width
  //
  it("leaves the width to the caller when inline", () => {
    expect(mount(BaseInput).classes()).toContain("w-full");
    expect(
      mount(BaseInput, { props: { inline: true } }).classes(),
    ).not.toContain("w-full");
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("BaseFormField", () => {
  // GIVEN: a field with a label, a hint and an error, holding an input
  //        bound through the slot props
  // WHEN:  it renders
  // THEN:  the label targets the input, the input is described by the
  //        hint and the error, is marked invalid, and the error is an
  //        alert
  //
  it("wires the label, hint and error to the control", () => {
    const wrapper = mount(BaseFormField, {
      props: { label: "Name", hint: "Your full name", error: "Required" },
      slots: {
        default: (p: { id: string; describedBy?: string; invalid: boolean }) =>
          h(BaseInput, {
            id: p.id,
            "aria-describedby": p.describedBy,
            invalid: p.invalid,
          }),
      },
    });
    const input = wrapper.get("input");
    const id = input.attributes("id")!;
    expect(wrapper.get("label").attributes("for")).toBe(id);
    expect(input.attributes("aria-describedby")).toBe(`${id}-hint ${id}-error`);
    expect(input.attributes("aria-invalid")).toBe("true");
    expect(wrapper.get('[role="alert"]').text()).toBe("Required");
    expect(wrapper.text()).toContain("Your full name");
  });

  // GIVEN: an optional field with no hint or error
  // WHEN:  it renders
  // THEN:  the label says "(optional)" and the input is not described
  //
  it("marks an optional field and omits empty descriptions", () => {
    const wrapper = mount(BaseFormField, {
      props: { label: "Memo", optional: true, id: "memo" },
      slots: {
        default: (p: { id: string; describedBy?: string }) =>
          h(BaseInput, { id: p.id, "aria-describedby": p.describedBy }),
      },
    });
    expect(wrapper.get("label").text()).toContain("(optional)");
    expect(wrapper.get("input").attributes("aria-describedby")).toBeUndefined();
    expect(wrapper.get("input").attributes("id")).toBe("memo");
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("BaseToggle", () => {
  // GIVEN: a toggle bound to a boolean inside a label
  // WHEN:  the user clicks the label
  // THEN:  the switch checkbox flips the model and the track turns to
  //        the accent
  //
  it("toggles its model from the surrounding label", async () => {
    const on = ref(false);
    const Host = defineComponent({
      setup: () => () =>
        h("label", [
          "Paused",
          h(BaseToggle, {
            modelValue: on.value,
            "onUpdate:modelValue": (v: boolean) => (on.value = v),
          }),
        ]),
    });
    const wrapper = mount(Host, { attachTo: document.body });
    const box = wrapper.get('input[role="switch"]');
    expect(wrapper.find(".bg-border-strong").exists()).toBe(true);

    await wrapper.get("label").trigger("click");
    expect(on.value).toBe(true);
    expect((box.element as HTMLInputElement).checked).toBe(true);
    expect(wrapper.find(".bg-accent").exists()).toBe(true);
  });
});
