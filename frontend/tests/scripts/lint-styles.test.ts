//
// lint-styles tests: each rule flags its violation with the line and a
// hint, and the allowed forms pass.
//

// 3rd party imports
//
import { describe, expect, it } from "vitest";

// app imports
//
import { lintSource } from "../../scripts/lint-styles.mjs";

////////////////////////////////////////////////////////////////////////
//
function rules(file: string, text: string): string[] {
  return lintSource(file, text).map((v) => `${v.line}:${v.rule}:${v.text}`);
}

////////////////////////////////////////////////////////////////////////
//
describe("lint-styles", () => {
  // GIVEN: a source line breaking one rule
  // WHEN:  it is linted
  // THEN:  that rule reports it, with the offending text
  //
  it.each([
    ["an arbitrary size", 'class="text-[13px]"', "arbitrary-value:text-[13px]"],
    [
      "an arbitrary variant width",
      'class="md:w-[420px]"',
      "arbitrary-value:md:w-[420px]",
    ],
    ["a palette colour", 'class="bg-ocean-400"', "palette-class:bg-ocean-400"],
    [
      "a stock colour with a variant",
      'class="hover:text-gray-700"',
      "palette-class:hover:text-gray-700",
    ],
    ["white", 'class="bg-white"', "palette-class:bg-white"],
    ["a hex colour", 'const c = "#1a2b3c";', "colour-literal:#1a2b3c"],
    ["an rgb() colour", 'const c = "rgb(0 0 0)";', "colour-literal:rgb(0"],
    ["a static style", '<div style="color: red" />', 'static-style:style="'],
    ["!important", ".x { color: inherit !important; }", "important:!important"],
  ])("flags %s", (_name, line, expected) => {
    const file = line.startsWith(".") ? "src/styles/x.css" : "src/views/X.vue";
    expect(rules(file, line)).toEqual([`1:${expected}`]);
  });

  // GIVEN: a `<style>` block in a view and in a base primitive
  // WHEN:  both are linted
  // THEN:  only the view is flagged
  //
  it("allows style blocks only in components/base", () => {
    const sfc = "<template />\n<style scoped>.a {}</style>";
    expect(rules("src/views/X.vue", sfc)).toEqual(["2:style-block:<style"]);
    expect(rules("src/components/base/BaseX.vue", sfc)).toEqual([]);
  });

  // GIVEN: token utilities, a bound `:style`, `rgb(var(--...))`, a slot
  //        shorthand, a comment, an allow comment, and hex in tokens.css
  // WHEN:  they are linted
  // THEN:  nothing is flagged
  //
  it("passes the allowed forms", () => {
    const sfc = [
      '<div class="bg-surface text-fg-muted rounded-card px-card-x" />',
      '<span :style="{ width: `${pct}%` }" />',
      '<template #default="{ id }"><i /></template>',
      "// #abcdef and bg-ocean-400 in a comment",
      "<!-- text-[13px] in a template comment -->",
      'const x = "text-[11px]"; // lint-styles-allow: demonstrating the allow comment',
      'const c = "rgb(var(--color-fg) / 0.5)";',
    ].join("\n");
    expect(rules("src/views/X.vue", sfc)).toEqual([]);
    expect(rules("src/styles/tokens.css", "--palette-x: #ffffff;")).toEqual([]);
  });

  // GIVEN: a violation
  // WHEN:  it is linted
  // THEN:  it carries a fix hint naming the token way
  //
  it("gives a fix hint", () => {
    const [v] = lintSource("src/views/X.vue", 'class="bg-ocean-400"');
    expect(v!.hint).toMatch(/semantic colour/);
  });
});
