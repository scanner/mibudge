<script setup lang="ts">
//
// BaseListRow -- one row of a list inside a BaseCard.  Presentational
// (base).
//
// The row lays its slot content out in a line with the card padding.
// `as="button"` (or `a`, or a `RouterLink`) makes the whole row
// actionable, with a hover tint; `chevron` adds the trailing arrow that
// marks a row which opens something.  Every row but the last draws a
// `border-subtle` divider below itself.  `align="start"` top-aligns the
// content for rows whose lines wrap.  Attributes and listeners land on
// the root.
//

// 3rd party imports
//
import { computed } from "vue";
import type { Component } from "vue";
import { IconChevronRight } from "@tabler/icons-vue";

////////////////////////////////////////////////////////////////////////
//
interface Props {
  as?: string | Component;
  chevron?: boolean;
  align?: "center" | "start";
}

const props = withDefaults(defineProps<Props>(), {
  as: "div",
  chevron: false,
  align: "center",
});

const interactive = computed(() => props.as !== "div" && props.as !== "li");
</script>

<template>
  <component
    :is="as"
    :type="as === 'button' ? 'button' : undefined"
    :class="[
      'flex w-full gap-3 border-b border-border-subtle px-card-x py-card-y text-left last:border-b-0',
      align === 'start' ? 'items-start' : 'items-center',
      interactive ? 'transition-colors hover:bg-surface-sunken' : '',
    ]"
  >
    <slot />
    <IconChevronRight
      v-if="chevron"
      class="size-icon-sm flex-none text-icon-muted"
      aria-hidden="true"
    />
  </component>
</template>
