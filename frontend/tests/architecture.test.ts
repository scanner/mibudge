//
// Architecture test: the SPA's layering rules, checked on the import
// statements of every file under `src/`.  See docs/spa/architecture.md
// for the layers and why the rules exist.
//
// Each file's imports are read from its source (`import ... from`,
// side-effect `import "..."`, dynamic `import("...")` and
// `export ... from`; for `.vue` files, the `<script>` blocks).  Relative
// imports are resolved to `@/...` so one rule covers both spellings.
// A rule names the files it applies to and the import prefixes those
// files must not use.
//

// 3rd party imports
//
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

////////////////////////////////////////////////////////////////////////
//
const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "../src");

const sources = import.meta.glob<string>("../src/**/*.{ts,vue}", {
  query: "?raw",
  import: "default",
  eager: true,
});

// `src`-relative path (`views/BudgetsView.vue`) → source text.
const files = new Map(
  Object.entries(sources).map(([path, text]) => [
    path.replace(/^\.\.\/src\//, ""),
    text,
  ]),
);

////////////////////////////////////////////////////////////////////////
//
const IMPORT_RE =
  /(?:^|\s)(?:import|export)\s[^'"]*?from\s*['"]([^'"]+)['"]|(?:^|\s)import\s*['"]([^'"]+)['"]|import\(\s*['"]([^'"]+)['"]\s*\)/g;

// The script part of a file: all `<script>` blocks of an SFC, or the
// whole file for `.ts`.
//
function scriptOf(path: string, text: string): string {
  if (!path.endsWith(".vue")) return text;
  return Array.from(
    text.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g),
    (m) => m[1],
  ).join("\n");
}

// Comments are dropped so an import mentioned in prose is not counted.
//
function stripComments(code: string): string {
  return code
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:"'`])\/\/.*$/gm, "$1");
}

// Import specifiers of a file, relative ones resolved to `@/...`.
//
function importsOf(path: string, text: string): string[] {
  const code = stripComments(scriptOf(path, text));
  return Array.from(code.matchAll(IMPORT_RE), (m) => m[1] ?? m[2] ?? m[3]).map(
    (spec) =>
      spec.startsWith(".")
        ? "@/" +
          relative(SRC, join(SRC, dirname(path), spec)).replace(/\\/g, "/")
        : spec,
  );
}

// Files that call the global `fetch`: bare, or through `window`,
// `globalThis` or `self`.  A method named `fetch` on anything else
// (`api.fetch(`) is not a call to it.
//
const FETCH_CALL_RE = /(^|[^.\w]|\b(?:window|globalThis|self)\.)fetch\s*\(/m;

function fetchCallers(sources: Map<string, string>): string[] {
  return [...sources]
    .filter(([, text]) => FETCH_CALL_RE.test(stripComments(text)))
    .map(([path]) => path);
}

function matches(spec: string, prefix: string): boolean {
  return spec === prefix || spec.startsWith(prefix + "/");
}

////////////////////////////////////////////////////////////////////////
//
interface Rule {
  name: string;
  appliesTo: (path: string) => boolean;
  forbidden: string[];
  // Exceptions to `forbidden`, e.g. a type-only module.
  allowed?: string[];
}

const under =
  (...dirs: string[]) =>
  (path: string) =>
    dirs.some((d) => path.startsWith(d + "/"));

const RULES: Rule[] = [
  {
    name: "domain/ is pure TypeScript",
    appliesTo: under("domain"),
    forbidden: [
      "vue",
      "pinia",
      "vue-router",
      "@/api",
      "@/stores",
      "@/components",
      "@/composables",
      "@/features",
      "@/models",
      "@/router",
      "@/views",
    ],
  },
  {
    name: "api/ does not depend on Vue, Pinia, the router or the layers above it",
    appliesTo: under("api"),
    forbidden: [
      "vue",
      "pinia",
      "vue-router",
      "@/stores",
      "@/components",
      "@/composables",
      "@/features",
      "@/models",
      "@/router",
      "@/views",
    ],
  },
  {
    name: "models/ maps DTOs to domain types only",
    appliesTo: under("models"),
    forbidden: [
      "vue",
      "pinia",
      "vue-router",
      "@/api",
      "@/stores",
      "@/components",
      "@/composables",
      "@/features",
      "@/router",
      "@/views",
    ],
    allowed: ["@/api/dto"],
  },
  {
    name: "composables/ are cross-feature behaviour, not data access",
    appliesTo: under("composables"),
    forbidden: [
      "@/api",
      "@/stores",
      "@/components",
      "@/features",
      "@/router",
      "@/views",
    ],
    allowed: ["@/api/errors"],
  },
  {
    name: "stores/ do not reach into the UI",
    appliesTo: under("stores"),
    forbidden: [
      "vue-router",
      "@/components",
      "@/features",
      "@/router",
      "@/views",
    ],
  },
  {
    name: "components/ are presentational",
    appliesTo: under("components"),
    forbidden: ["@/api", "@/stores", "vue-router", "@/features", "@/views"],
  },
  {
    name: "views/ never call the API",
    appliesTo: under("views"),
    forbidden: ["@/api"],
  },
  {
    name: "features/ do not import views",
    appliesTo: under("features"),
    forbidden: ["@/views"],
  },
];

////////////////////////////////////////////////////////////////////////
//
// Violations of `rule`: `"<file> imports <specifier>"` for each.
//
function violations(rule: Rule, sourceFiles: Map<string, string>): string[] {
  const out: string[] = [];
  for (const [path, text] of sourceFiles) {
    if (!rule.appliesTo(path)) continue;
    for (const spec of importsOf(path, text)) {
      if (rule.allowed?.some((a) => matches(spec, a))) continue;
      if (rule.forbidden.some((f) => matches(spec, f)))
        out.push(`${path} imports ${spec}`);
    }
  }
  return out;
}

////////////////////////////////////////////////////////////////////////
//
describe("architecture", () => {
  // GIVEN: the source tree
  // WHEN:  it is scanned
  // THEN:  every layer is present (the rules are not vacuous)
  //
  it("finds files in every layer", () => {
    for (const dir of [
      "domain",
      "api",
      "models",
      "stores",
      "composables",
      "features",
      "components",
      "views",
    ]) {
      expect([...files.keys()].some(under(dir)), dir).toBe(true);
    }
  });

  // GIVEN: a layering rule
  // WHEN:  every file it applies to is scanned
  // THEN:  none imports what the rule forbids
  //
  it.each(RULES.map((r) => [r.name, r] as const))("%s", (_name, rule) => {
    expect(violations(rule, files)).toEqual([]);
  });

  // GIVEN: the source tree
  // WHEN:  it is scanned for `fetch(` calls
  // THEN:  the only one is in `api/http.ts`
  //
  it("calls fetch only in api/http.ts", () => {
    expect(fetchCallers(files)).toEqual(["api/http.ts"]);
  });

  // GIVEN: sources that call the global `fetch` in each spelling, and
  //        ones that only call a method named `fetch`
  // WHEN:  they are scanned for `fetch(` calls
  // THEN:  the global calls are reported and the method calls are not
  //
  it("finds every spelling of a global fetch call", () => {
    const sources = new Map([
      ["bare.ts", "await fetch(url);"],
      ["window.ts", "await window.fetch(url);"],
      ["globalThis.ts", "await globalThis.fetch(url);"],
      ["self.ts", "await self.fetch(url);"],
      ["method.ts", "await api.fetch(url);\nawait store.fetchList();"],
      ["commented.ts", "// await window.fetch(url);"],
    ]);
    expect(fetchCallers(sources)).toEqual([
      "bare.ts",
      "window.ts",
      "globalThis.ts",
      "self.ts",
    ]);
  });

  // GIVEN: sources that break a rule, in each import style
  // WHEN:  they are checked
  // THEN:  each is reported, and the allowed exception is not
  //
  it("reports violations", () => {
    const bad = new Map([
      [
        "components/Bad.vue",
        '<script setup lang="ts">\nimport { api } from "@/api";\n</script>',
      ],
      [
        "views/Bad.vue",
        '<script setup lang="ts">\nconst m = import("../api/http");\n</script>',
      ],
      [
        "domain/bad.ts",
        'import { ref } from "vue";\nexport * from "../stores/session";',
      ],
      ["models/ok.ts", 'import type { BudgetDto } from "@/api/dto";'],
      [
        "components/Commented.vue",
        '<script setup lang="ts">\n// import { api } from "@/api";\n</script>',
      ],
    ]);
    const found = RULES.flatMap((rule) => violations(rule, bad));
    expect(found).toEqual([
      "domain/bad.ts imports vue",
      "domain/bad.ts imports @/stores/session",
      "components/Bad.vue imports @/api",
      "views/Bad.vue imports @/api/http",
    ]);
  });
});
