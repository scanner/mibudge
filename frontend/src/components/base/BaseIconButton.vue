<script setup lang="ts">
//
// BaseIconButton -- a round button whose only content is an icon.
// Presentational (base).
//
// `label` is required and becomes the `aria-label`, since the icon is
// the button's only visible content.  `size` is `sm` (28px, inside
// cards and rows) or `md` (40px, in the TopBar and page headers).
// Its hit area is at least `tap-min` (`.tap-target`), so a 28px button
// is still a 44px target; keep neighbours 44px apart centre to centre.
// `tone="danger"` tints the hover for destructive actions.  `pressed`
// makes it a toggle: it sets `aria-pressed` and fills the button with
// the accent while on.  The icon goes in the default slot.
//

// 3rd party imports
//
import { computed } from "vue";

////////////////////////////////////////////////////////////////////////
//
interface Props {
  label: string;
  size?: "sm" | "md";
  tone?: "default" | "danger";
  pressed?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  size: "md",
  tone: "default",
  pressed: undefined,
});

const classes = computed(() => [
  "tap-target inline-flex flex-none items-center justify-center rounded-pill transition-colors",
  props.size === "sm" ? "h-7 w-7" : "h-10 w-10",
  props.pressed
    ? "bg-accent text-fg-on-accent hover:bg-accent-hover"
    : props.tone === "danger"
      ? "text-fg-muted hover:bg-danger-bg hover:text-danger-fg"
      : "text-fg-muted hover:bg-surface-muted hover:text-fg",
]);
</script>

<template>
  <button
    type="button"
    :aria-label="label"
    :aria-pressed="pressed"
    :class="classes"
  >
    <slot />
  </button>
</template>
