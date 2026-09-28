<script setup lang="ts">
//
// BaseSkeleton -- a pulsing placeholder block shown while content
// loads.  Presentational (base).
//
// The caller sets its size with classes (`class="h-16"`); `shape` is
// `card` (the card radius, for placeholder cards) or `line` (the small
// radius, for a line of text).  It is hidden from screen readers.
//

////////////////////////////////////////////////////////////////////////
//
interface Props {
  shape?: "card" | "line";
}

withDefaults(defineProps<Props>(), { shape: "card" });
</script>

<template>
  <div
    aria-hidden="true"
    :class="[
      'animate-pulse bg-surface-muted',
      shape === 'card' ? 'rounded-card' : 'rounded-xs',
    ]"
  />
</template>
