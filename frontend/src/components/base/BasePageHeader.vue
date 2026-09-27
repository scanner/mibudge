<script setup lang="ts">
//
// BasePageHeader -- a page's title.  Presentational (base).
//
// Renders the page's one `h1` in the `text-page-title` role, with the
// `actions` slot at its trailing edge.
//

////////////////////////////////////////////////////////////////////////
//
interface Props {
  title: string;
}

defineProps<Props>();
</script>

<template>
  <div class="mb-5 flex items-center justify-between gap-3">
    <h1 class="text-page-title text-fg">{{ title }}</h1>
    <slot name="actions" />
  </div>
</template>
