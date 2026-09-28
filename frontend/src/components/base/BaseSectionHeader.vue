<script setup lang="ts">
//
// BaseSectionHeader -- the small uppercase heading above a group of
// cards or rows ("BUDGETS", "CONFIGURATION").  Presentational (base).
//
// It is the one place the `text-overline` role is applied.  `as` sets
// the heading level (default `h2`; `div` for a label that is not a
// heading).  `card` makes it the header strip across the top of a
// BaseCard: card padding and a divider below.  The `actions` slot holds
// a trailing control such as a "See all" link.
//

////////////////////////////////////////////////////////////////////////
//
interface Props {
  title: string;
  as?: string;
  card?: boolean;
}

withDefaults(defineProps<Props>(), { as: "h2", card: false });
</script>

<template>
  <div
    :class="[
      'flex items-center justify-between gap-3',
      card ? 'border-b border-border-subtle px-card-x py-card-y' : '',
    ]"
  >
    <component :is="as" class="text-overline uppercase text-fg-muted">
      {{ title }}
    </component>
    <slot name="actions" />
  </div>
</template>
