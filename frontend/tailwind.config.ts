//
// Tailwind CSS configuration for mibudge.
//
// The theme's colours, font sizes, radii, shadows, z-index and motion
// are replaced, not extended: each utility names a semantic token from
// `src/styles/tokens.css` (`text-fg-muted`, `text-label`, `rounded-card`,
// `z-sheet`), never a raw value.  Tailwind's numeric spacing scale is
// kept, with named aliases added.  Colour entries read the token's RGB
// channels so the `/<alpha>` modifier works.  See `docs/spa/styling.md`.
//

import type { Config } from "tailwindcss";
import forms from "@tailwindcss/forms";
import plugin from "tailwindcss/plugin";

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

type Weight = "regular" | "medium" | "semibold";

////////////////////////////////////////////////////////////////////////
//
// A typography role: one `text-<role>` class sets size, line height,
// weight and (where the role has one) letter spacing.
//
function role(
  name: string,
  weight: Weight,
  tracking = false,
): [string, Record<string, string>] {
  return [
    `var(--text-${name})`,
    {
      lineHeight: `var(--leading-${name})`,
      fontWeight: `var(--weight-${weight})`,
      ...(tracking ? { letterSpacing: `var(--tracking-${name})` } : {}),
    },
  ];
}

const fontSize = {
  "display-amount": role("display-amount", "medium"),
  "title-amount": role("title-amount", "medium"),
  amount: role("amount", "medium"),
  "amount-sm": role("amount-sm", "regular"),
  "page-title": role("page-title", "medium"),
  title: role("title", "medium"),
  "item-title": role("item-title", "medium"),
  body: role("body", "regular"),
  "body-sm": role("body-sm", "regular"),
  label: role("label", "medium"),
  meta: role("meta", "regular"),
  overline: role("overline", "semibold", true),
  badge: role("badge", "semibold", true),
  input: role("input", "regular"),
};

const config: Config = {
  content: ["./index.html", "./src/**/*.{vue,ts,tsx}"],
  theme: {
    colors,
    fontSize,
    // A bare `border` / `divide-*` and a bare `ring` use these defaults.
    borderColor: ({ theme }) => ({
      ...theme("colors"),
      DEFAULT: token("border"),
    }),
    ringColor: ({ theme }) => ({
      ...theme("colors"),
      DEFAULT: token("border-focus"),
    }),
    borderRadius: {
      none: "0",
      xs: "var(--radius-xs)",
      control: "var(--radius-control)",
      card: "var(--radius-card)",
      pill: "9999px",
    },
    boxShadow: {
      none: "none",
      raised: "var(--shadow-raised)",
      control: "var(--shadow-control)",
      overlay: "var(--shadow-overlay)",
    },
    zIndex: {
      auto: "auto",
      sticky: "10",
      nav: "30",
      sheet: "40",
      dialog: "50",
    },
    transitionDuration: {
      DEFAULT: "var(--duration-fast)",
      fast: "var(--duration-fast)",
      base: "var(--duration-base)",
      slow: "var(--duration-slow)",
    },
    transitionTimingFunction: {
      DEFAULT: "var(--ease-standard)",
      standard: "var(--ease-standard)",
      enter: "var(--ease-enter)",
      exit: "var(--ease-exit)",
    },
    extend: {
      fontFamily: {
        sans: ['"IBM Plex Sans"', "system-ui", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "monospace"],
      },
      spacing: {
        "page-x": "var(--space-page-x)",
        "card-x": "var(--space-card-x)",
        "card-y": "var(--space-card-y)",
        "stack-sm": "var(--space-stack-sm)",
        "stack-md": "var(--space-stack-md)",
        section: "var(--space-section)",
        "icon-xs": "var(--size-icon-xs)",
        "icon-sm": "var(--size-icon-sm)",
        "icon-md": "var(--size-icon-md)",
        "icon-lg": "var(--size-icon-lg)",
        "tap-min": "var(--size-tap-min)",
        topbar: "var(--size-topbar)",
        bottomnav: "var(--size-bottomnav)",
        sheet: "var(--size-sheet)",
        "progress-sm": "var(--size-progress-sm)",
        "progress-md": "var(--size-progress-md)",
        "progress-lg": "var(--size-progress-lg)",
      },
      maxHeight: {
        sheet: "var(--size-sheet-max-height)",
      },
      borderWidth: {
        rule: "var(--width-rule)",
      },
      transitionProperty: {
        width: "width",
      },
    },
  },
  plugins: [
    forms,
    // `can-hover:` applies only on a device with a hovering pointer, so
    // content revealed on hover stays visible on touch screens.
    plugin(({ addVariant }) => {
      addVariant("can-hover", "@media (hover: hover)");
    }),
  ],
};

export default config;
