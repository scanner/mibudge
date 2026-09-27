<script setup lang="ts">
//
// BaseCardSection -- one padded block inside a BaseCard, divided from
// the block below it.  Presentational (base).
//
// Every section but the last draws a `border-subtle` rule below
// itself, so a card of sections needs no divider markup.
//
</script>

<template>
  <div
    class="border-b border-border-subtle px-card-x py-card-y last:border-b-0"
  >
    <slot />
  </div>
</template>
