<script setup lang="ts">
//
// BaseCard -- the outlined white card every grouped surface sits on.
// Presentational (base).
//
// `padded` gives it the card padding (`card-x` / `card-y`); leave it off
// when the card holds BaseListRows or BaseCardSections, which pad
// themselves.  `as` renders the card as another element (`section`,
// `ul`, `button`).  Attributes and listeners land on the root.
//

// 3rd party imports
//
import type { Component } from "vue";

////////////////////////////////////////////////////////////////////////
//
interface Props {
  padded?: boolean;
  as?: string | Component;
}

withDefaults(defineProps<Props>(), { padded: false, as: "div" });
</script>

<template>
  <component
    :is="as"
    :class="[
      'overflow-hidden rounded-card border border-border bg-surface',
      padded ? 'px-card-x py-card-y' : '',
    ]"
  >
    <slot />
  </component>
</template>
