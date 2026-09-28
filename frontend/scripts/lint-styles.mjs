#!/usr/bin/env node
//
// Style lint for the SPA: every colour, size and style comes from the
// design tokens (`src/styles/tokens.css`) through their Tailwind
// utilities or a `Base*` primitive.  See `docs/spa/styling.md`.
//
// `pnpm lint:styles` scans `src/**/*.{vue,ts,css}` and fails, with
// `file:line`, the offending text and a fix hint, on:
//
//   colour-literal    a hex, `rgb()` or `hsl()` colour outside tokens.css
//   arbitrary-value   a Tailwind arbitrary value such as `text-[13px]`
//   palette-class     a raw palette or stock colour class (`bg-ocean-400`,
//                     `text-neutral-500`, `text-gray-700`, `bg-white`)
//   static-style      a static `style="..."` attribute (`:style` bound to
//                     a computed value is allowed)
//   style-block       a `<style>` block in an SFC outside components/base/
//   important         `!important`
//
// A line ending in a `lint-styles-allow: <reason>` comment is skipped.
// Comments are not checked.  `lintSource()` is exported for the tests.
//

// system imports
//
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

////////////////////////////////////////////////////////////////////////
//
// Tailwind arbitrary values that are allowed.  Add an entry only with a
// reason; prefer adding a token.
//
export const ARBITRARY_ALLOWLIST = new Set([]);

const PALETTE = [
  "ocean", "mint", "amber", "coral", "neutral", "gray", "slate", "zinc",
  "stone", "red", "orange", "yellow", "lime", "green", "emerald", "teal",
  "cyan", "sky", "blue", "indigo", "violet", "purple", "fuchsia", "pink",
  "rose", "white", "black",
];
const COLOR_UTILS = [
  "text", "bg", "border", "border-[xytrbl]", "ring", "ring-offset",
  "divide", "outline", "fill", "stroke", "from", "via", "to",
  "placeholder", "decoration", "accent", "caret", "shadow",
];

const RULES = [
  {
    id: "colour-literal",
    re: /#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\(\s*\d/g,
    skipFile: (file) => file.endsWith(`styles${sep}tokens.css`) || file.endsWith("styles/tokens.css"),
    // `<template #name>` is Vue slot shorthand, not a colour.
    skipMatch: (line, index) => /#[\w-]+\s*(=|>|$)/.test(line.slice(index)) && /<template\b[^>]*$/.test(line.slice(0, index)),
    hint: "use a colour token (`text-fg-muted`, `bg-danger-bg`); add one to tokens.css if none fits",
  },
  {
    id: "arbitrary-value",
    re: /(?<![\w-])(?:[a-z0-9-]+:)*[a-z][a-z0-9-]*-\[[^\]\s]+\]/g,
    skipMatch: (_line, _index, match) => ARBITRARY_ALLOWLIST.has(match),
    hint: "use a token utility (`text-meta`, `max-h-sheet`); add a token if none fits",
  },
  {
    id: "palette-class",
    re: new RegExp(
      `(?<![\\w-])(?:[a-z0-9-]+:)*(?:${COLOR_UTILS.join("|")})-(?:${PALETTE.join("|")})(?:-\\d{2,3})?(?:\\/\\d+)?(?![\\w-])`,
      "g",
    ),
    hint: "use the semantic colour for the role (`bg-surface`, `text-fg-on-accent`, `border-border`)",
  },
  {
    id: "static-style",
    re: /(?<![:\w-])style="/g,
    onlyExt: [".vue"],
    hint: "use utility classes; bind `:style` only for a genuinely dynamic value",
  },
  {
    id: "style-block",
    re: /<style\b/g,
    onlyExt: [".vue"],
    skipFile: (file) => file.includes(`components${sep}base${sep}`) || file.includes("components/base/"),
    hint: "put shared CSS in src/styles/ or a Base* primitive; use utilities in components",
  },
  {
    id: "important",
    re: /!important/g,
    hint: "remove `!important`; fix the specificity or use the token/primitive",
  },
];

////////////////////////////////////////////////////////////////////////
//
// Blank out comments while keeping line numbers, so they are not
// checked.  Handles `//`, `/* */` and `<!-- -->`.
//
function stripComments(text, ext) {
  const blank = (m) => m.replace(/[^\n]/g, " ");
  let out = text.replace(/<!--[\s\S]*?-->/g, blank);
  out = out.replace(/\/\*[\s\S]*?\*\//g, blank);
  if (ext !== ".css") {
    out = out.replace(/(^|[^:"'`\\])\/\/[^\n]*/g, (m, pre) => pre + blank(m.slice(pre.length)));
  }
  return out;
}

////////////////////////////////////////////////////////////////////////
//
export function lintSource(file, text) {
  const ext = file.slice(file.lastIndexOf("."));
  const rawLines = text.split("\n");
  const lines = stripComments(text, ext).split("\n");
  const violations = [];
  for (const rule of RULES) {
    if (rule.onlyExt && !rule.onlyExt.includes(ext)) continue;
    if (rule.skipFile && rule.skipFile(file)) continue;
    lines.forEach((line, i) => {
      if (/lint-styles-allow:\s*\S/.test(rawLines[i])) return;
      for (const m of line.matchAll(rule.re)) {
        if (rule.skipMatch && rule.skipMatch(line, m.index, m[0])) continue;
        violations.push({ file, line: i + 1, rule: rule.id, text: m[0], hint: rule.hint });
      }
    });
  }
  return violations.sort((a, b) => a.line - b.line);
}

////////////////////////////////////////////////////////////////////////
//
function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return walk(path);
    return /\.(vue|ts|css)$/.test(name) && !name.endsWith(".d.ts") ? [path] : [];
  });
}

////////////////////////////////////////////////////////////////////////
//
function main() {
  const root = fileURLToPath(new URL("..", import.meta.url));
  const src = join(root, "src");
  const violations = walk(src).flatMap((path) =>
    lintSource(relative(root, path), readFileSync(path, "utf8")),
  );
  for (const v of violations) {
    console.log(`${v.file}:${v.line}: ${v.rule}: \`${v.text}\` -- ${v.hint}`);
  }
  if (violations.length) {
    console.log(`\n${violations.length} style violation(s).  See docs/spa/styling.md.`);
    process.exit(1);
  }
  console.log("lint:styles: no violations");
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) main();
