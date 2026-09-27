<script setup lang="ts">
//
// BaseBadge -- a small uppercase tag on a row ("PENDING", "SPLIT").
// Presentational (base).
//
// `tone` is `warning` or `neutral`.  `variant="outline"` (the default)
// draws a thin ring for use inside dense rows; `variant="soft"` fills
// the tag with the tone's tint, for use on its own.
//

// 3rd party imports
//
import { computed } from "vue";

////////////////////////////////////////////////////////////////////////
//
interface Props {
  tone?: "warning" | "neutral";
  variant?: "outline" | "soft";
}

const props = withDefaults(defineProps<Props>(), {
  tone: "neutral",
  variant: "outline",
});

const classes = computed(() => {
  const outline = props.variant === "outline";
  const tone =
    props.tone === "warning"
      ? outline
        ? "text-warning-fg ring-1 ring-warning-border"
        : "bg-warning-bg text-warning-fg"
      : outline
        ? "text-fg-muted ring-1 ring-border-emphasis"
        : "bg-surface-muted text-fg-muted";
  return [
    "inline-flex flex-none items-center px-1 py-0.5 text-badge uppercase",
    outline ? "rounded-xs" : "rounded-pill px-2",
    tone,
  ];
});
</script>

<template>
  <span :class="classes"><slot /></span>
</template>
