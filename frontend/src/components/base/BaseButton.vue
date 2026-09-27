<script setup lang="ts">
//
// BaseButton -- the app's one button.  Presentational (base).
//
// `variant` sets the role: `primary` (the accent fill), `secondary`
// (outlined), `danger` (the danger fill), `danger-secondary` (outlined
// in the danger colour), `ghost` (accent text on a tint when hovered),
// `link` and `link-danger` (text only, no padding).  `size` is `sm` or
// `md`.  `as` renders the same styles on an `a` or a `RouterLink`;
// every other attribute and listener lands on the rendered element.
// `loading` disables the button and marks it busy.
//

// 3rd party imports
//
import { computed } from "vue";
import type { Component } from "vue";

////////////////////////////////////////////////////////////////////////
//
export type ButtonVariant =
  | "primary"
  | "secondary"
  | "danger"
  | "danger-secondary"
  | "ghost"
  | "link"
  | "link-danger";

interface Props {
  variant?: ButtonVariant;
  size?: "sm" | "md";
  block?: boolean;
  loading?: boolean;
  disabled?: boolean;
  as?: string | Component;
  type?: "button" | "submit" | "reset";
}

const props = withDefaults(defineProps<Props>(), {
  variant: "primary",
  size: "md",
  block: false,
  loading: false,
  disabled: false,
  as: "button",
  type: "button",
});

////////////////////////////////////////////////////////////////////////
//
// Hover styles apply only while the button is enabled (`enabled:`);
// `a` and `RouterLink` have no enabled state, so they take plain
// `hover:`.  Both forms are written out so Tailwind generates them.
//
interface VariantClasses {
  base: string;
  hover: string;
  enabledHover: string;
  disabled: string;
}

// A disabled filled button turns grey, a clear change of state; the
// others fade to half opacity.
const FILLED_DISABLED = "disabled:bg-surface-strong disabled:text-fg-disabled";
const FADED_DISABLED = "disabled:opacity-50";

const VARIANTS: Record<ButtonVariant, VariantClasses> = {
  primary: {
    base: "bg-accent text-fg-on-accent",
    hover: "hover:bg-accent-hover",
    enabledHover: "enabled:hover:bg-accent-hover",
    disabled: FILLED_DISABLED,
  },
  secondary: {
    base: "border border-border bg-surface text-fg",
    hover: "hover:bg-surface-sunken",
    enabledHover: "enabled:hover:bg-surface-sunken",
    disabled: FADED_DISABLED,
  },
  danger: {
    base: "bg-danger-solid text-fg-on-accent",
    hover: "hover:bg-danger-solid-hover",
    enabledHover: "enabled:hover:bg-danger-solid-hover",
    disabled: FILLED_DISABLED,
  },
  "danger-secondary": {
    base: "border border-danger-solid bg-surface text-danger-fg",
    hover: "hover:bg-danger-bg",
    enabledHover: "enabled:hover:bg-danger-bg",
    disabled: FADED_DISABLED,
  },
  ghost: {
    base: "text-accent-fg",
    hover: "hover:bg-accent-subtle",
    enabledHover: "enabled:hover:bg-accent-subtle",
    disabled: FADED_DISABLED,
  },
  link: {
    base: "text-fg-link",
    hover: "hover:text-accent-hover",
    enabledHover: "enabled:hover:text-accent-hover",
    disabled: FADED_DISABLED,
  },
  "link-danger": {
    base: "text-danger-fg",
    hover: "hover:text-danger-solid-hover",
    enabledHover: "enabled:hover:text-danger-solid-hover",
    disabled: FADED_DISABLED,
  },
};

const isButton = computed(() => props.as === "button");
const isLink = computed(
  () => props.variant === "link" || props.variant === "link-danger",
);

const classes = computed(() => {
  const v = VARIANTS[props.variant];
  const hover = isButton.value ? v.enabledHover : v.hover;
  const shape = isLink.value
    ? props.size === "sm"
      ? "text-meta font-medium"
      : "text-label"
    : [
        "justify-center rounded-control text-label",
        props.size === "sm" ? "px-3 py-2" : "px-4 py-2.5",
      ];
  return [
    "inline-flex items-center gap-1.5 transition-colors disabled:cursor-not-allowed",
    shape,
    v.base,
    hover,
    v.disabled,
    props.block ? "w-full" : "",
  ];
});
</script>

<template>
  <component
    :is="as"
    :type="isButton ? type : undefined"
    :disabled="isButton ? disabled || loading : undefined"
    :aria-busy="loading || undefined"
    :class="classes"
  >
    <slot />
  </component>
</template>
