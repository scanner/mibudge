//
// Tailwind CSS configuration for mibudge.
//
// `theme.colors` is replaced, not extended: the only colour utilities
// are the semantic tokens defined in `src/styles/tokens.css`, so a class
// names a role (`text-fg-muted`, `bg-danger-bg`) and never a raw shade.
// Each entry reads the token's RGB channels so the `/<alpha>` modifier
// works.  See `docs/spa/styling.md` for what each token is for.
//

import type { Config } from "tailwindcss";
import forms from "@tailwindcss/forms";

////////////////////////////////////////////////////////////////////////
//
function token(name: string): string {
  return `rgb(var(--color-${name}) / <alpha-value>)`;
}

////////////////////////////////////////////////////////////////////////
//
// A status `-border` is drawn at `--alpha-status-border` (set once in
// `tokens.css`); an `/<alpha>` modifier scales that alpha further.
//
function statusBorder(status: string): string {
  return `rgb(var(--color-${status}-border) / calc(var(--alpha-status-border) * <alpha-value>))`;
}

////////////////////////////////////////////////////////////////////////
//
function status(name: string): Record<string, string> {
  return {
    bg: token(`${name}-bg`),
    fg: token(`${name}-fg`),
    border: statusBorder(name),
    solid: token(`${name}-solid`),
  };
}

const colors = {
  transparent: "transparent",
  current: "currentColor",
  inherit: "inherit",
  fg: {
    DEFAULT: token("fg"),
    muted: token("fg-muted"),
    subtle: token("fg-subtle"),
    disabled: token("fg-disabled"),
    "on-accent": token("fg-on-accent"),
    link: token("fg-link"),
  },
  icon: {
    muted: token("icon-muted"),
  },
  canvas: token("canvas"),
  surface: {
    DEFAULT: token("surface"),
    sunken: token("surface-sunken"),
    muted: token("surface-muted"),
    strong: token("surface-strong"),
  },
  scrim: token("scrim"),
  border: {
    DEFAULT: token("border"),
    subtle: token("border-subtle"),
    emphasis: token("border-emphasis"),
    strong: token("border-strong"),
    focus: token("border-focus"),
  },
  accent: {
    DEFAULT: token("accent"),
    hover: token("accent-hover"),
    subtle: token("accent-subtle"),
    fg: token("accent-fg"),
    border: token("accent-border"),
  },
  success: status("success"),
  warning: status("warning"),
  danger: {
    ...status("danger"),
    "solid-hover": token("danger-solid-hover"),
  },
  info: status("info"),
  money: {
    positive: token("money-positive"),
    negative: token("money-negative"),
  },
  progress: {
    funded: token("progress-funded"),
    active: token("progress-active"),
    behind: token("progress-behind"),
    over: token("progress-over"),
    paused: token("progress-paused"),
    track: token("progress-track"),
  },
  row: {
    pending: token("row-pending"),
    unallocated: token("row-unallocated"),
  },
};

const config: Config = {
  content: ["./index.html", "./src/**/*.{vue,ts,tsx}"],
  theme: {
    colors,
    // A bare `border` / `divide-*` and a bare `ring` use these defaults.
    borderColor: ({ theme }) => ({
      ...theme("colors"),
      DEFAULT: token("border"),
    }),
    ringColor: ({ theme }) => ({
      ...theme("colors"),
      DEFAULT: token("border-focus"),
    }),
    extend: {
      fontFamily: {
        sans: ['"IBM Plex Sans"', "system-ui", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "monospace"],
      },
      borderRadius: {
        card: "14px",
        subcard: "10px",
      },
    },
  },
  plugins: [forms],
};

export default config;
