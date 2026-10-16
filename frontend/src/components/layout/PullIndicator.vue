<script setup lang="ts">
//
// PullIndicator -- the pull-to-refresh mark under the TopBar.
// Presentational: the shell passes the pull `distance` (px), whether
// releasing now would refresh (`ready`), and whether a refresh is
// running.  The mark turns with the pull and takes the accent once
// `ready`; while refreshing it is a spinner.
//

// 3rd party imports
//
import { IconRefresh } from "@tabler/icons-vue";

////////////////////////////////////////////////////////////////////////
//
defineProps<{
  distance: number;
  ready: boolean;
  refreshing: boolean;
}>();
</script>

<template>
  <div
    v-if="refreshing || distance > 0"
    class="pointer-events-none flex justify-center overflow-hidden"
    :class="refreshing ? 'h-12' : ''"
    :style="refreshing ? undefined : { height: `${distance}px` }"
    role="status"
    :aria-label="refreshing ? 'Refreshing' : 'Pull to refresh'"
  >
    <span
      v-if="refreshing"
      class="mt-3 h-5 w-5 animate-spin rounded-pill border-2 border-border border-t-accent"
    />
    <IconRefresh
      v-else
      class="mt-3 size-icon-md"
      :class="ready ? 'text-accent-fg' : 'text-fg-subtle'"
      :style="{ transform: `rotate(${distance * 3}deg)` }"
    />
  </div>
</template>
